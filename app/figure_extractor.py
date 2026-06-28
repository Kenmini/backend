"""PDF図解の単一ページ抽出とRekognitionによるラベル検出モジュール（英語ラベルのみ）。

処理の流れ:
  1. S3 からPDFをダウンロード
  2. PyMuPDF で指定ページだけをPNG画像に変換
  3. 画像を S3 の `figures/` プレフィックス下にアップロード（キャッシュ用途）
  4. Amazon Rekognition の detect_labels でラベルを取得
  5. 英語ラベルのリストを返す
"""

import logging

import boto3
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def extract_page_labels(
    pdf_s3_key: str,
    bucket: str,
    page_number: int,
    region: str = "us-east-1",
    figures_prefix: str = "figures",
    min_confidence: float = 70.0,
    max_labels: int = 10,
    dpi: int = 150,
) -> list[str]:
    """
    S3 上のPDFの指定ページを画像化し、Rekognition で英語ラベルを検出して返す。

    Parameters
    ----------
    pdf_s3_key:
        S3 バケット内のPDFのキー（バケット名を除く）
    bucket:
        S3 バケット名
    page_number:
        抽出するページ番号（1-indexed, Bedrockのメタデータに準拠）
    region:
        AWS リージョン
    figures_prefix:
        S3 への画像保存先プレフィックス
    min_confidence:
        Rekognition で採用するラベルの最低信頼度（0-100）
    max_labels:
        最大ラベル数
    dpi:
        ページ画像の解像度

    Returns
    -------
    list[str]
        Rekognition が検出した英語ラベルのリスト（信頼度の高い順）
    """
    s3 = boto3.client("s3", region_name=region)
    rek = boto3.client("rekognition", region_name=region)

    # キャッシュキー: figures/page_<ページ番号>.png
    page_idx = max(0, page_number - 1)  # 0-indexed に変換
    s3_image_key = f"{figures_prefix}/{pdf_s3_key.replace('/', '_')}_page_{page_number:04d}.png"

    # 1. S3 から PDF をダウンロード
    logger.info("s3_download_start", extra={"bucket": bucket, "key": pdf_s3_key})
    pdf_obj = s3.get_object(Bucket=bucket, Key=pdf_s3_key)
    pdf_bytes = pdf_obj["Body"].read()

    # 2. PyMuPDF で指定ページのみを PNG 化
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)

    if page_idx >= total_pages:
        logger.warning(
            "page_out_of_range",
            extra={"page_number": page_number, "total_pages": total_pages},
        )
        page_idx = total_pages - 1  # 最後のページにフォールバック

    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    page = doc[page_idx]
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()

    # 3. S3 に画像をアップロード（キャッシュとして保存）
    s3.put_object(
        Bucket=bucket,
        Key=s3_image_key,
        Body=img_bytes,
        ContentType="image/png",
    )
    logger.info("figure_uploaded", extra={"s3_key": s3_image_key})

    # 4. Rekognition でラベル検出
    rek_resp = rek.detect_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": s3_image_key}},
        MaxLabels=max_labels,
        MinConfidence=min_confidence,
    )
    labels = [lbl["Name"] for lbl in rek_resp.get("Labels", [])]
    logger.info(
        "rekognition_labels_detected",
        extra={
            "page_number": page_number,
            "labels": labels,
            "s3_image_key": s3_image_key,
        },
    )
    return labels
