import asyncio
import json
import os
import time
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aio_pika
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

MZINGA_URL = os.getenv("MZINGA_URL", "http://localhost:3000")
MZINGA_EMAIL = os.getenv("MZINGA_EMAIL")
MZINGA_PASSWORD = os.getenv("MZINGA_PASSWORD")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")
RABBITMQ_URL = os.getenv("RABBITMQ_URL")
ROUTING_KEY = os.getenv("ROUTING_KEY")
EXCHANGE_NAME = os.getenv("EXCHANGE_NAME")
QUEUE_NAME = os.getenv("QUEUE_NAME")

# Authentication
def authenticate() -> str:
    log.info("Authenticating against MZinga...")
    response = requests.post(
        f"{MZINGA_URL}/api/users/login",
        json={"email": MZINGA_EMAIL, "password": MZINGA_PASSWORD},
    )
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise RuntimeError("No token in login response")
    log.info("Authentication successful")
    return token


def make_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

# REST API calls
def fetch_pending(token: str) -> list:
    response = requests.get(
        f"{MZINGA_URL}/api/communications",
        params={"where[status][equals]": "pending", "depth": "1"},
        headers=make_headers(token),
    )
    if response.status_code == 401:
        raise PermissionError("401")
    response.raise_for_status()
    return response.json().get("docs", [])


def patch_status(token: str, doc_id: str, status: str):
    response = requests.patch(
        f"{MZINGA_URL}/api/communications/{doc_id}",
        json={"status": status},
        headers=make_headers(token),
    )
    if response.status_code == 401:
        raise PermissionError("401")
    response.raise_for_status()

def serialize_node(node: dict) -> str:
    if "text" in node:
        text = node["text"]
        if not text:
            return ""
        if node.get("bold"):
            text = f"<strong>{text}</strong>"
        if node.get("italic"):
            text = f"<em>{text}</em>"
        if node.get("underline"):
            text = f"<u>{text}</u>"
        return text

    node_type = node.get("type", "paragraph")
    children_html = "".join(serialize_node(c) for c in node.get("children", []))

    tag_map = {
        "paragraph": "p",
        "h1": "h1",
        "h2": "h2",
        "h3": "h3",
        "ul": "ul",
        "ol": "ol",
        "li": "li",
    }

    if node_type in tag_map:
        tag = tag_map[node_type]
        return f"<{tag}>{children_html}</{tag}>"

    if node_type == "link":
        url = node.get("url", "#")
        return f'<a href="{url}">{children_html}</a>'

    return children_html


def serialize_body(body: list) -> str:
    return "".join(serialize_node(node) for node in body)

# Recipient extraction
def extract_emails(relationships: list) -> list[str]:
    if not relationships:
        return []
    emails = []
    for rel in relationships:
        value = rel.get("value")
        if isinstance(value, dict):
            email = value.get("email")
            if email:
                emails.append(email)
    return emails

def send_email(to_list: list, cc_list: list, bcc_list: list, subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject

    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    msg.attach(MIMEText(html, "html"))

    all_recipients = to_list + cc_list + bcc_list

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.sendmail(EMAIL_FROM, all_recipients, msg.as_string())

def process_document(token: str, doc: dict) -> str:
    doc_id = doc["id"]
    log.info("Processing document %s", doc_id)

    try:
        patch_status(token, doc_id, "processing")
    except PermissionError:
        token = authenticate()
        patch_status(token, doc_id, "processing")

    try:
        to_emails = extract_emails(doc.get("tos") or [])
        cc_emails = extract_emails(doc.get("ccs") or [])
        bcc_emails = extract_emails(doc.get("bccs") or [])

        if not to_emails:
            raise ValueError("No valid 'to' email addresses found")

        html = serialize_body(doc.get("body") or [])
        subject = doc.get("subject", "(no subject)")

        log.info("Sending to: %s", to_emails)
        send_email(to_emails, cc_emails, bcc_emails, subject, html)

        try:
            patch_status(token, doc_id, "sent")
        except PermissionError:
            token = authenticate()
            patch_status(token, doc_id, "sent")

        log.info("Document %s marked sent", doc_id)

    except Exception as e:
        log.error("Failed to process document %s: %s", doc_id, e)
        try:
            patch_status(token, doc_id, "failed")
        except PermissionError:
            token = authenticate()
            patch_status(token, doc_id, "failed")
    
def poll_main():
    token = authenticate()

    log.info("Worker started — polling every %s seconds", POLL_INTERVAL)

    while True:
        try:
            docs = fetch_pending(token)
            if docs:
                for doc in docs:
                    token = process_document(token, doc)
            else:
                log.debug("No pending documents, sleeping...")
                time.sleep(POLL_INTERVAL)

        except PermissionError:
            log.warning("Token expired, re-authenticating...")
            token = authenticate()

        except Exception as e:
            log.error("Unexpected error in poll loop: %s", e)
            time.sleep(POLL_INTERVAL)


# Event-driven main loop (Part B)
async def event_main():
    token = authenticate()

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)

        exchange = await channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC,
            durable=True, internal=True, auto_delete=False,
        )

        queue = await channel.declare_queue(QUEUE_NAME, durable=True)
        await queue.bind(exchange, routing_key=ROUTING_KEY)

        log.info(f"Subscribed to {EXCHANGE_NAME} with key {ROUTING_KEY}. Waiting for messages.")

        async with queue.iterator() as messages:
            async for message in messages:
                async with message.process(requeue=True):
                    try:
                        body = json.loads(message.body.decode())
                        event_data = body.get("data", {})
                        operation = event_data.get("operation")
                        doc_id = (event_data.get("doc") or {}).get("id")

                        if not doc_id:
                            log.warning("Message missing doc.id, skipping")
                            continue

                        if operation != "create":
                            log.debug(f"Ignoring operation={operation} for {doc_id}")
                            continue

                        response = requests.get(
                            f"{MZINGA_URL}/api/communications/{doc_id}",
                            params={"depth": 1},
                            headers=make_headers(token),
                        )
                        if response.status_code == 401:
                            log.warning("Token expired, re-authenticating")
                            token = authenticate()
                            raise PermissionError("401")
                        response.raise_for_status()
                        doc = response.json()
                        token = process_document(token, doc)

                    except requests.HTTPError as e:
                        if e.response.status_code == 401:
                            log.warning("Token expired, re-authenticating")
                            token = authenticate()
                            raise
                        else:
                            log.error(f"HTTP error processing message: {e}")
                            raise
                    except PermissionError:
                        log.warning("Token expired, re-authenticating...")
                        token = authenticate()
                        raise


if __name__ == "__main__":
    if RABBITMQ_URL and ROUTING_KEY and EXCHANGE_NAME and QUEUE_NAME:
        log.info("RabbitMQ environment detected — starting in event-driven mode")
        asyncio.run(event_main())
    else:
        log.info("Polling environment — starting in polling mode")
        poll_main()
