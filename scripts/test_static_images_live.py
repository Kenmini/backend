"""Live integration test: verify static images are returned for known pages,
and check what happens when a page has no static images."""

import json

from fastapi.testclient import TestClient

from app.api import create_app
from config import Settings


def main():
    s = Settings.from_env()
    app = create_app(settings=s)
    client = TestClient(app)

    print("=" * 70)
    print("Test 1: Question about flashing (expect page 4 static images)")
    print("=" * 70)
    r = client.post("/ask", json={
        "message": "フラッシングの手順を教えてください",
        "session_id": "test-static-1",
    })
    data = r.json()
    print(f"Status: {r.status_code}")
    print(f"Answer: {data['answer_text'][:120]}...")
    print(f"is_gap: {data['is_gap']}")
    vd = data["visual_data"]
    print(f"Page: {vd['page_number']}")
    print(f"Source: {vd['source']}")
    print(f"image_url (base64): {vd['image_url']}")
    print(f"Static images: {len(vd['static_images'])}")
    for img in vd["static_images"]:
        print(f"  - {img['filename']}: {img['name']}")
        print(f"    URL prefix: {img['image_url'][:90]}...")
        print(f"    Highlights: {list(img['highlights'].keys())}")
    print()

    print("=" * 70)
    print("Test 2: Question about sample holder (expect page 3, multiple images)")
    print("=" * 70)
    r2 = client.post("/ask", json={
        "message": "試料ホルダーの挿入方法を教えてください",
        "session_id": "test-static-2",
    })
    data2 = r2.json()
    print(f"Status: {r2.status_code}")
    print(f"Answer: {data2['answer_text'][:120]}...")
    vd2 = data2["visual_data"]
    print(f"Page: {vd2['page_number']}")
    print(f"Static images: {len(vd2['static_images'])}")
    for img in vd2["static_images"]:
        print(f"  - {img['filename']}")
    print()

    print("=" * 70)
    print("Test 3: Question that might hit a page WITHOUT static images")
    print("=" * 70)
    r3 = client.post("/ask", json={
        "message": "液体窒素の補給頻度は？",
        "session_id": "test-static-3",
    })
    data3 = r3.json()
    print(f"Status: {r3.status_code}")
    print(f"Answer: {data3['answer_text'][:120]}...")
    vd3 = data3["visual_data"]
    print(f"Page: {vd3['page_number']}")
    print(f"Source: {vd3['source']}")
    print(f"image_url (base64): {vd3['image_url']}")
    print(f"Static images: {len(vd3['static_images'])}")
    pdf_url = vd3.get("pdf_url")
    if pdf_url:
        print(f"PDF fallback URL: {pdf_url[:100]}...")
    else:
        print("PDF fallback URL: None")
    if not vd3["static_images"]:
        print("  >> No static images for this page.")
        print("     Frontend can use pdf_url + page_number to render the PDF page.")
    print()

    print("=" * 70)
    print("Test 4: English question (cross-language retrieval)")
    print("=" * 70)
    r4 = client.post("/ask", json={
        "message": "How do I insert the sample holder?",
        "session_id": "test-static-4",
    })
    data4 = r4.json()
    print(f"Status: {r4.status_code}")
    print(f"Answer: {data4['answer_text'][:120]}...")
    vd4 = data4["visual_data"]
    print(f"Page: {vd4['page_number']}")
    print(f"Static images: {len(vd4['static_images'])}")
    for img in vd4["static_images"]:
        print(f"  - {img['filename']}: {img['name']}")
    pdf_url4 = vd4.get("pdf_url")
    if pdf_url4:
        print(f"PDF fallback URL: {pdf_url4[:100]}...")
    print()

    print("=" * 70)
    print("Test 5: Question likely to hit page 1 or 9 (NO static images)")
    print("=" * 70)
    r5 = client.post("/ask", json={
        "message": "NBD分析の手順は？",
        "session_id": "test-static-5",
    })
    data5 = r5.json()
    print(f"Status: {r5.status_code}")
    print(f"Answer: {data5['answer_text'][:120]}...")
    vd5 = data5["visual_data"]
    print(f"Page: {vd5['page_number']}")
    print(f"Static images: {len(vd5['static_images'])}")
    pdf_url5 = vd5.get("pdf_url")
    if pdf_url5:
        print(f"PDF fallback URL (presigned): {pdf_url5[:100]}...")
    else:
        print("PDF fallback URL: None")
    if not vd5["static_images"] and pdf_url5:
        print("  >> No static images, but frontend can load the PDF directly!")
    print()


if __name__ == "__main__":
    main()
