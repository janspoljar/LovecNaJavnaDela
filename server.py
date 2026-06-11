"""
server.py — Flask API strežnik za jn-watchdog.
Registracija naročnikov, Stripe webhooki, odjava in health check.
"""

import re
import json
import sqlite3
import logging

import stripe
from flask import Flask, request, jsonify
from flask_cors import CORS

import config
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Omogoči CORS za vse origine

# Inicializiraj bazo ob importu — gunicorn ne izvede __main__ bloka,
# init_db je idempotenten (CREATE TABLE IF NOT EXISTS), zato je klic varen.
db.init_db()

stripe.api_key = config.STRIPE_SECRET_KEY

# Preprost regex za validacijo email naslova
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.route("/registracija", methods=["POST"])
def registracija():
    """
    Registracija novega naročnika.
    Pričakuje JSON: {"email": "...", "kategorije": ["IT & Software", ...]}
    Ustvari Stripe customer in checkout session za naročnino.
    """
    podatki = request.get_json(silent=True) or {}
    email = (podatki.get("email") or "").strip().lower()
    kategorije = podatki.get("kategorije")

    # Validacija vhodnih podatkov
    if not email or not EMAIL_REGEX.match(email):
        return jsonify({"napaka": "Neveljaven email naslov."}), 400
    if not isinstance(kategorije, list) or not kategorije:
        return jsonify({"napaka": "Kategorije morajo biti neprazen seznam."}), 400

    # Dodaj uporabnika v bazo (aktiven = 0 dokler ne plača)
    db.dodaj_uporabnika(email, kategorije)

    try:
        # Ustvari Stripe customer in shrani ID v bazo
        customer = stripe.Customer.create(email=email)
        db.nastavi_stripe_customer(email, customer.id)

        # Ustvari checkout session za mesečno naročnino
        seja = stripe.checkout.Session.create(
            customer=customer.id,
            mode="subscription",
            line_items=[{"price": config.STRIPE_PRICE_ID, "quantity": 1}],
            success_url="https://tvojadomena.si/uspeh?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://tvojadomena.si/preklicano",
        )
    except stripe.error.StripeError as e:
        logger.error(f"Stripe napaka pri registraciji {email}: {e}")
        return jsonify({"napaka": "Napaka pri povezavi s plačilnim sistemom."}), 502

    logger.info(f"Registracija uspešna, checkout ustvarjen za: {email}")
    return jsonify({"checkout_url": seja.url}), 200


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    """
    Stripe webhook — aktivira uporabnika ob plačilu,
    deaktivira ob preklicu naročnine.
    """
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, config.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error(f"Neveljaven webhook: {e}")
        return jsonify({"napaka": "Neveljaven webhook podpis."}), 400

    if event["type"] == "checkout.session.completed":
        seja = event["data"]["object"]
        # Email je lahko v customer_details ali customer_email
        email = (seja.get("customer_details") or {}).get("email") or seja.get("customer_email")
        if email:
            db.aktiviraj_uporabnika(email.lower())
            logger.info(f"Naročnina aktivirana: {email}")

    elif event["type"] == "customer.subscription.deleted":
        narocnina = event["data"]["object"]
        customer_id = narocnina.get("customer")
        # Poišči email po stripe_customer_id in deaktiviraj
        email = _email_po_customer_id(customer_id)
        if email:
            db.deaktiviraj_uporabnika(email)
            logger.info(f"Naročnina prekinjena: {email}")
        else:
            logger.warning(f"Ni uporabnika za customer_id: {customer_id}")

    return jsonify({"status": "ok"}), 200


def _email_po_customer_id(customer_id: str) -> str | None:
    """Vrne email uporabnika glede na Stripe customer ID, ali None."""
    if not customer_id:
        return None
    conn = sqlite3.connect(config.DB_PATH)
    vrstica = conn.execute(
        "SELECT email FROM uporabniki WHERE stripe_customer_id = ?", (customer_id,)
    ).fetchone()
    conn.close()
    return vrstica[0] if vrstica else None


@app.route("/odjava", methods=["GET"])
def odjava():
    """Odjava uporabnika prek linka v emailu."""
    email = (request.args.get("email") or "").strip().lower()
    if email:
        db.deaktiviraj_uporabnika(email)
    return (
        "<html><body style='font-family: Arial; text-align: center; padding: 60px;'>"
        "<h2>Uspešno odjavljen.</h2>"
        "<p>Žal nam je ker odhajate.</p>"
        "</body></html>"
    ), 200


@app.route("/zdravje", methods=["GET"])
def zdravje():
    """Health check za Railway — vrne stanje baze."""
    conn = sqlite3.connect(config.DB_PATH)
    narocila = conn.execute("SELECT COUNT(*) FROM narocila").fetchone()[0]
    aktivni = conn.execute("SELECT COUNT(*) FROM uporabniki WHERE aktiven = 1").fetchone()[0]
    conn.close()
    return jsonify({
        "status": "ok",
        "narocila_v_bazi": narocila,
        "aktivni_uporabniki": aktivni,
    }), 200


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=config.PORT)
