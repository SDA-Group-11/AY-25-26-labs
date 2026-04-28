import os
import time
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

MONGODB_URI = os.getenv("MONGODB_URI")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")

# Slate AST → HTML serializer
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

# Recipient resolution
def resolve_emails(db, relationships: list) -> list[str]:
    if not relationships:
        return []

    ids = []
    for rel in relationships:
        value = rel.get("value")
        if value:
            ids.append(str(value))

    if not ids:
        return []

    users = db["users"].find(
        {"_id": {"$in": [ObjectId(i) for i in ids]}},
        {"email": 1}
    )
    return [u["email"] for u in users if "email" in u]

# Email sending
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

# Main poll loop
def process_document(db, doc: dict):
    doc_id = doc["_id"]
    log.info("Processing document %s", doc_id)

    db["communications"].update_one(
        {"_id": doc_id},
        {"$set": {"status": "processing"}}
    )

    try:
        to_emails = resolve_emails(db, doc.get("tos") or [])
        cc_emails = resolve_emails(db, doc.get("ccs") or [])
        bcc_emails = resolve_emails(db, doc.get("bccs") or [])

        if not to_emails:
            raise ValueError("No valid 'to' email addresses found")

        html = serialize_body(doc.get("body") or [])
        subject = doc.get("subject", "(no subject)")

        log.info("Sending to: %s", to_emails)
        send_email(to_emails, cc_emails, bcc_emails, subject, html)

        db["communications"].update_one(
            {"_id": doc_id},
            {"$set": {"status": "sent"}}
        )
        log.info("Document %s marked sent", doc_id)

    except Exception as e:
        log.error("Failed to process document %s: %s", doc_id, e)
        db["communications"].update_one(
            {"_id": doc_id},
            {"$set": {"status": "failed"}}
        )


def main():
    log.info("Connecting to MongoDB at %s", MONGODB_URI)
    client = MongoClient(MONGODB_URI)
    db = client["mzinga"]
    log.info("Worker started — polling every %s seconds", POLL_INTERVAL)

    while True:
        doc = db["communications"].find_one({"status": "pending"})
        if doc:
            process_document(db, doc)
        else:
            log.debug("No pending documents, sleeping...")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()