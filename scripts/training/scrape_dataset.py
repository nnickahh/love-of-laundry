"""
scrape_dataset.py
Downloads flat-lay garment images from Bing Image Search using icrawler.
Uses shorter, more direct queries for better image quality.
"""
import os
import time
import logging
from icrawler.builtin import BingImageCrawler, GoogleImageCrawler

# Silence icrawler noise
logging.getLogger("icrawler").setLevel(logging.ERROR)

RAW_DIR = "dataset/raw"

# ── Class-specific search queries ────────────────────────────────────────────
QUERIES = {
    "shirt": [
        "school uniform shirt white collared flat lay",
        "school uniform polo shirt flat lay clothing",
        "formal button down shirt flat lay clothing",
        "t-shirt flat lay product photo",
        "white collared dress shirt flat lay",
        "polo shirt flat lay photography",
        "short sleeve school uniform shirt flat lay",
    ],
    "jacket": [
        "winter jacket flat lay clothing product photo",
        "hoodie sweater flat lay photography clothing",
        "winter coat thick outerwear flat lay",
        "denim jacket flat lay clothing",
        "bomber jacket zipper flat lay isolated",
    ],
    "jeans": [
        "school uniform pants trousers slacks flat lay",
        "black school trousers flat lay clothing",
        "navy blue uniform pants flat lay",
        "jeans flat lay product photography",
        "denim pants flat lay clothing",
        "chinos slacks trousers flat lay white background",
    ],
    "underwear": [
        "underwear flat lay product photography",
        "boxer briefs flat lay product photo",
        "underwear briefs flat lay white background",
        "socks pair flat lay product photo",
    ],
    "dress": [
        "women dress flat lay product photography",
        "sundress flat lay clothing white background",
        "floral maxi dress flat lay isolated",
        "evening gown dress flat lay clothing",
        "one piece dress flat lay product",
    ],
    "hole": [
        "shirt with hole damage clothing",
        "torn shirt hole worn out fabric",
        "jeans hole damage worn out",
        "clothing hole fabric defect",
        "worn out shirt hole damage garment",
    ],
    "tear": [
        "ripped torn clothing fabric tear",
        "shirt tear rip damage fabric",
        "torn jeans ripped fabric",
        "ripped shirt tear damage garment",
        "fabric rip tear worn clothing",
    ],
    "stain": [
        "stained white shirt clothing",
        "stain on clothing fabric",
        "dirty stained shirt fabric",
        "clothing stain mark fabric",
        "stained garment clothing dirty",
    ],
}

MAX_PER_QUERY = 40   # 40 × 5 queries = up to 200 per class


def scrape_class(class_name: str, queries: list[str], max_per_query: int = MAX_PER_QUERY):
    out_dir = os.path.join(RAW_DIR, class_name)
    os.makedirs(out_dir, exist_ok=True)

    for i, query in enumerate(queries):
        print(f"  [{class_name}] query {i+1}/{len(queries)}: '{query}'")
        try:
            crawler = BingImageCrawler(
                downloader_threads=6,
                storage={"root_dir": out_dir}
            )
            crawler.crawl(
                keyword=query,
                max_num=max_per_query,
                file_idx_offset="auto",
                filters={"size": "medium"},
            )
        except Exception as e:
            print(f"    Bing failed ({e}), trying Google...")
            try:
                crawler = GoogleImageCrawler(
                    downloader_threads=4,
                    storage={"root_dir": out_dir}
                )
                crawler.crawl(
                    keyword=query,
                    max_num=max_per_query,
                    file_idx_offset="auto",
                )
            except Exception as e2:
                print(f"    Google also failed: {e2}")
        time.sleep(1)

    total = len([f for f in os.listdir(out_dir)
                 if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp'))])
    print(f"  [{class_name}] Total images: {total}")
    return total


def main():
    print("=" * 60)
    print("  Garment Dataset Scraper  (v2 — improved queries)")
    print("=" * 60)
    os.makedirs(RAW_DIR, exist_ok=True)

    summary = {}
    for class_name, queries in QUERIES.items():
        print(f"\n-- {class_name.upper()} --")
        n = scrape_class(class_name, queries)
        summary[class_name] = n

    print("\n" + "=" * 60)
    print("Scraping complete! Summary:")
    total_imgs = 0
    for cls, n in summary.items():
        tag = "GARMENT" if cls in {"shirt","jacket","jeans","underwear","dress"} else "DEFECT "
        print(f"  [{tag}] {cls:12}: {n:4d} images")
        total_imgs += n
    print(f"\n  TOTAL: {total_imgs} images across {len(summary)} classes")
    print("=" * 60)
    print("\nNext step: run  python auto_annotate.py")


if __name__ == "__main__":
    main()
