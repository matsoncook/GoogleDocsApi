#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
from typing import List

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]

SEPARATOR = "\n" + ("-" * 72) + "\n\n"


def get_credentials() -> Credentials:
    """
    Load stored credentials (token.json) or perform OAuth flow against credentials.json.
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError(
                    "credentials.json not found. Download OAuth client credentials from "
                    "Google Cloud Console and place the file next to this script."
                )
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            # Opens a browser for consent, then returns to localhost.
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds


def gather_text_files(
    directory: Path, pattern: str, sort: str
) -> List[Path]:
    files = list(directory.rglob(pattern))
    if sort == "name":
        files.sort(key=lambda p: p.name.lower())
    elif sort == "mtime":
        files.sort(key=lambda p: p.stat().st_mtime)
    elif sort == "ctime":
        files.sort(key=lambda p: p.stat().st_ctime)
    return files


def read_file_text(p: Path, encoding: str) -> str:
    try:
        return p.read_text(encoding=encoding, errors="replace")
    except Exception as e:
        return f"[Error reading {p}: {e}]\n"


def build_combined_text(files: List[Path], base_dir: Path, encoding: str) -> str:
    parts = []
    for f in files:
        rel = f.relative_to(base_dir) if f.is_relative_to(base_dir) else f
        header = f"### {rel.as_posix()} ###\n\n"
        body = read_file_text(f, encoding)
        parts.append(header + body + SEPARATOR)
    return "".join(parts).rstrip() + "\n"


def chunk_text(s: str, max_len: int = 45000) -> List[str]:
    """
    Break text into chunks to keep each Docs API insert request a safe size.
    """
    return [s[i : i + max_len] for i in range(0, len(s), max_len)] if s else []


def create_google_doc(title: str, creds: Credentials) -> str:
    docs = build("docs", "v1", credentials=creds)
    doc = docs.documents().create(body={"title": title}).execute()
    return doc["documentId"]


def append_text_to_doc(doc_id: str, text: str, creds: Credentials) -> None:
    docs = build("docs", "v1", credentials=creds)
    # Use endOfSegmentLocation to always append at the end
    for piece in chunk_text(text):
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "endOfSegmentLocation": {},
                            "text": piece,
                        }
                    }
                ]
            },
        ).execute()


def main():
    parser = argparse.ArgumentParser(
        description="Amalgamate all text files in a directory into a Google Doc."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing text files.",
    )
    parser.add_argument(
        "--pattern",
        default="*.txt",
        help="Glob pattern for text files (default: *.txt). Use '**/*.txt' to recurse.",
    )
    parser.add_argument(
        "--title",
        default="Amalgamated Text Files",
        help="Title for the Google Doc to create.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="File encoding to read (default: utf-8).",
    )
    parser.add_argument(
        "--sort",
        choices=["name", "mtime", "ctime"],
        default="name",
        help="Sort files by: name | mtime | ctime (default: name).",
    )
    parser.add_argument(
        "--recurse",
        action="store_true",
        help="Recurse into subdirectories (equivalent to using pattern='**/*.txt').",
    )
    args = parser.parse_args()

    base_dir = args.directory.resolve()
    if not base_dir.exists():
        raise SystemExit(f"Directory not found: {base_dir}")

    pattern = "**/*.txt" if args.recurse and args.pattern == "*.txt" else args.pattern

    files = gather_text_files(base_dir, pattern, args.sort)
    if not files:
        raise SystemExit("No files matched the pattern.")

    combined = build_combined_text(files, base_dir, args.encoding)

    creds = get_credentials()
    doc_id = create_google_doc(args.title, creds)
    append_text_to_doc(doc_id, combined, creds)

    # Provide a Drive link (Docs URLs follow this pattern)
    print(f"Created Google Doc: https://docs.google.com/document/d/{doc_id}/edit")


if __name__ == "__main__":
    main()
