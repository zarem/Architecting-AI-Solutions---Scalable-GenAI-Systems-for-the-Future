import hashlib
import heapq
import logging
import os
import re
import secrets
import sqlite3
import textwrap

from cryptography.fernet import Fernet


DOCUMENT_PATH = "./data/i-have-a-dream.txt"
FREE_USER_SIZE_LIMIT = 10_240
SUMMARY_LINE_WIDTH = 80

STOP_WORDS = set(
    """a an the and or but if while of to in on at by for with about against
    between into through during before after above below from up down out off
    over under again further then once here there when where why how all any
    both each few more most other some such no nor not only own same so than
    too very s t can will just don should now is are was were be been being it
    its this that these those i you he she they we as have has had do does did
    which who whom""".split()
)


# Application and data layers: in-memory users and feedback.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    force=True,
)

connection = sqlite3.connect(":memory:")
cursor = connection.cursor()
cursor.execute("CREATE TABLE users (username TEXT, password TEXT, role TEXT)")
cursor.execute("CREATE TABLE feedback (summary TEXT, feedback TEXT)")

cursor.execute(
    "INSERT INTO users VALUES ('user1', ?, 'free')",
    (hashlib.sha256("password1".encode()).hexdigest(),),
)
cursor.execute(
    "INSERT INTO users VALUES ('user2', ?, 'premium')",
    (hashlib.sha256("password2".encode()).hexdigest(),),
)
connection.commit()


# Infrastructure layer: simulated cloud storage and encryption.
cloud_storage = {"documents": []}
encryption_key = Fernet.generate_key()
cipher_suite = Fernet(encryption_key)


def encrypt_document(document):
    """Encrypt a document before processing or storage."""
    print("🔐 Encrypting document...")
    return cipher_suite.encrypt(document.encode())


def decrypt_document(encrypted_document):
    """Decrypt a document before summarization."""
    print("🔓 Decrypting document...")
    return cipher_suite.decrypt(encrypted_document).decode()


# Model layer: local extractive summarizer provided for the Colab lab.
def gpt3_summarize(document, num_sentences=3):
    """Return the highest-scoring sentences from a document."""
    text = re.sub(r"\s+", " ", document).strip()
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if len(sentence.split()) > 3
    ]

    if not sentences:
        return text[:300]

    frequencies = {}
    for word in re.findall(r"[a-z']+", text.lower()):
        if word not in STOP_WORDS and len(word) > 2:
            frequencies[word] = frequencies.get(word, 0) + 1

    if not frequencies:
        return " ".join(sentences[:num_sentences])

    peak_frequency = max(frequencies.values())
    normalized_frequencies = {
        word: count / peak_frequency for word, count in frequencies.items()
    }

    scores = {}
    for index, sentence in enumerate(sentences):
        words = re.findall(r"[a-z']+", sentence.lower())
        if 4 <= len(words) <= 45:
            scores[index] = sum(
                normalized_frequencies.get(word, 0) for word in words
            ) / (len(words) ** 0.5)

    top_indexes = sorted(
        heapq.nlargest(num_sentences, scores, key=scores.get)
    )
    return " ".join(sentences[index] for index in top_indexes)


async def login():
    """Authenticate a simulated user and return the assigned role."""
    username = input("Username: ")
    password_hash = hashlib.sha256(input("Password: ").encode()).hexdigest()

    cursor.execute(
        "SELECT role FROM users WHERE username = ? AND password = ?",
        (username, password_hash),
    )
    result = cursor.fetchone()

    if not result:
        logging.error("Invalid credentials!")
        return None, None, None

    token = secrets.token_hex(16)
    logging.info("User %s authenticated successfully.", username)
    return username, result[0], token


# Gate and pipeline: validate, encrypt, and route the document.
async def upload_document(role, token):
    """Validate and route a document based on the user's role."""
    print("\n📄 Upload a document:")

    try:
        document_size = os.path.getsize(DOCUMENT_PATH)
        logging.info("Document size: %s bytes", document_size)
    except FileNotFoundError:
        logging.error("File %s not found.", DOCUMENT_PATH)
        return
    except OSError as error:
        logging.error("Could not read the document size: %s", error)
        return

    if role == "free" and document_size > FREE_USER_SIZE_LIMIT:
        raise PermissionError("Document size exceeds limit for free users.")

    with open(DOCUMENT_PATH, "r", encoding="utf-8") as document_file:
        document = document_file.read()

    encrypted_document = encrypt_document(document)

    if role == "free":
        print("✅ Document uploaded for real-time processing.")
        await summarize_document(encrypted_document)
    else:
        cloud_storage["documents"].append(encrypted_document)
        logging.info("Document uploaded for batch processing.")


async def summarize_document(encrypted_document):
    """Decrypt, summarize, display, and collect feedback."""
    document = decrypt_document(encrypted_document)
    summary = gpt3_summarize(document)

    print("\n📝 Summary:")
    print(textwrap.fill(summary, width=SUMMARY_LINE_WIDTH))

    await gather_feedback(summary)


async def gather_feedback(summary):
    """Validate and store feedback for a generated summary."""
    print("\n💬 How was the summary?")
    feedback = input("Enter feedback (good/bad): ").strip().lower()

    if feedback not in {"good", "bad"}:
        logging.error("Invalid feedback!")
        return

    cursor.execute("INSERT INTO feedback VALUES (?, ?)", (summary, feedback))
    connection.commit()
    logging.info("Feedback stored: %s", feedback)


async def start_simulation():
    """Run the interactive login and document-upload pipeline."""
    _, user_role, token = await login()

    if not user_role:
        logging.error("Login failed. Please try again.")
        return

    while True:
        try:
            await upload_document(user_role, token)
        except PermissionError as error:
            logging.error(error)

        choice = input("Do you want to continue? (yes/no): ").strip().lower()
        if choice == "no":
            logging.info("Exiting simulation. Thanks for your feedback!")
            break


async def batch_processing():
    """Summarize documents queued by premium users."""
    if not cloud_storage["documents"]:
        return

    logging.info("Batch processing premium-user documents.")
    for encrypted_document in cloud_storage["documents"]:
        await summarize_document(encrypted_document)
    cloud_storage["documents"].clear()


async def main():
    """Run the simulation and any queued batch processing."""
    await start_simulation()
    await batch_processing()


# Colab supports top-level await when this file is loaded into a notebook cell.
await main()

cursor.execute("SELECT * FROM feedback")
logging.info("Feedback received so far: %s", cursor.fetchall())
