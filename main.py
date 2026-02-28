from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware

from database import engine, SessionLocal
from models import Base, User, Subscription

import os
import shutil
import requests
from extractor import process_financial_statement


app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key="supersecretkey123"
)
Base.metadata.create_all(bind=engine)
# ===============================
# Static & Templates Setup
# ===============================

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

UPLOAD_FOLDER = "uploaded_files"
OUTPUT_FOLDER = "output_files"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ===============================
# Home Page
# ===============================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    user_id = request.session.get("user_id")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "logged_in": True if user_id else False
        }
    )
@app.get("/login-page", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register-page", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

# ===============================
# Upload & Process PDF
# ===============================

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, file.filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        output_file = process_financial_statement(file_path)

        return FileResponse(
            output_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="income_statement.xlsx"
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Processing failed: {str(e)}"}
        )

# ===============================
# Pricing Page
# ===============================

@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    return templates.TemplateResponse("pricing.html", {"request": request})

# ===============================
# PayPal Sandbox Configuration
# ===============================

PAYPAL_CLIENT_ID = "AV1ix0iDUNSbIsmr1sDF5uRexjVIv-jdjTyf5NiZmpdAzDSsfIUgvsIllKflr57eWILy-T4yAc1SnJSV"
PAYPAL_SECRET = "EKnuV791Ed3aYAaou8c8dyab1uQB39AEBnlJUK3aZkp_JVrkNoijrdtklv-B95D_SVWU9suwK9_x2owS"
PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"

def get_paypal_access_token():
    url = f"{PAYPAL_BASE_URL}/v1/oauth2/token"

    response = requests.post(
        url,
        headers={"Accept": "application/json"},
        data={"grant_type": "client_credentials"},
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
    )

    if response.status_code != 200:
        raise Exception("Failed to get PayPal access token")

    return response.json().get("access_token")

# ===============================
# Create PayPal Order
# ===============================

@app.api_route("/create-paypal-order/{plan}", methods=["GET", "POST"])
async def create_paypal_order(plan: str):

    plan_prices = {
        "pro": "999.00",
        "enterprise": "4999.00"
    }

    if plan not in plan_prices:
        return JSONResponse(status_code=400, content={"error": "Invalid plan"})

    access_token = get_paypal_access_token()

    url = f"{PAYPAL_BASE_URL}/v2/checkout/orders"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }

    data = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {
                "currency_code": "USD",
                "value": plan_prices[plan]
            }
        }],
        "application_context": {
            "return_url": "http://127.0.0.1:8000/payment-success",
            "cancel_url": "http://127.0.0.1:8000/pricing"
        }
    }

    response = requests.post(url, json=data, headers=headers)

    if response.status_code not in [200, 201]:
        return JSONResponse(status_code=400, content={"error": "Order creation failed"})

    order = response.json()

    for link in order.get("links", []):
        if link.get("rel") == "approve":
            return {"approval_url": link.get("href")}

    return JSONResponse(status_code=400, content={"error": "Approval URL not found"})

# ===============================
# Capture Payment After Approval
# ===============================

@app.get("/payment-success", response_class=HTMLResponse)
async def payment_success(request: Request, token: str = None):

    if not token:
        return JSONResponse(status_code=400, content={"error": "Missing PayPal token"})

    access_token = get_paypal_access_token()

    capture_url = f"{PAYPAL_BASE_URL}/v2/checkout/orders/{token}/capture"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }

    response = requests.post(capture_url, headers=headers)

    if response.status_code != 201:
        return JSONResponse(status_code=400, content={"error": "Payment capture failed"})

    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "message": "Payment completed successfully!",
            "order_id": token
        }
    )

# ===============================
# Health Check
# ===============================

@app.get("/health")
async def health_check():
    return {"status": "Application running successfully"}

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

from database import SessionLocal
from models import User
from fastapi import Form

@app.post("/register")
async def register(email: str = Form(...), password: str = Form(...)):

    db = SessionLocal()

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        return RedirectResponse("/register-page", status_code=302)

    new_user = User(
        email=email,
        password=hash_password(password)
    )

    db.add(new_user)
    db.commit()
    db.close()

    return RedirectResponse("/login-page", status_code=302)

from fastapi.responses import RedirectResponse

@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password):
        return RedirectResponse("/login-page", status_code=302)

    request.session["user_id"] = user.id
    db.close()

    return RedirectResponse("/", status_code=302)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out successfully"}

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):

    user_id = request.session.get("user_id")

    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not logged in"})

    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()

    subscription = db.query(Subscription).filter(
        Subscription.user_id == user_id
    ).first()

    db.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "email": user.email,
            "plan": subscription.plan if subscription else "Free",
            "status": subscription.status if subscription else "Inactive"
        }
    )