import os, sys, shutil
from pathlib import Path
from PIL import Image

TARGET_CLASSES = [
    'shirt', 'jacket', 'jeans', 'underwear', 'dress',
    'hole', 'tear', 'stain', 'broken_button', 'color_defect',
    'foreign_yarn', 'button_hike', 'swing_error', 'shorts', 'skirt'
]

DEEPFASHION_MAP = {
    'tee': 0, 't-shirt': 0, 'top': 0, 'blouse': 0, 'shirt': 0, 'polo': 0,
    'tank': 0, 'jersey': 0, 'henley': 0, 'sweater': 0, 'cardigan': 0,
    'turtleneck': 0, 'hoodie': 0, 'sweatshirt': 0, 'flannel': 0,
    'jacket': 1, 'coat': 1, 'blazer': 1, 'parka': 1, 'bomber': 1,
    'anorak': 1, 'vest': 1, 'cape': 1, 'peacoat': 1, 'overcoat': 1,
    'jeans': 2, 'pants': 2, 'trousers': 2, 'sweatpants': 2, 'leggings': 2,
    'joggers': 2, 'capris': 2, 'chinos': 2, 'slacks': 2, 'jeggings': 2,
    'shorts': 13, 'trunks': 13, 'bermudas': 13, 'boxers': 13, 'cutoffs': 13,
    'dress': 4, 'gown': 4, 'jumpsuit': 4, 'romper': 4, 'kaftan': 4, 'kimono': 4, 'robe': 4,
    'skirt': 14
}

def convert_bbox(x1, y1, x2, y2, img_w, img_h):
    x1 = max(0, min(img_w, x1))
    y1 = max(0, min(img_h, y1))
    x2 = max(0, min(img_w, x2))
    y2 = max(0, min(img_h, y2))
    bw, bh = x2 - x1, y2 - y1
    if bw <= 2 or bh <= 2: return None
    return (x1 + bw/2.0)/img_w, (y1 + bh/2.0)/img_h, bw/img_w, bh/img_h

def parse_deepfashion(root_dir, out_dir='dataset/deepfashion_converted', max_samples=15000):
    root = Path(root_dir)
    out = Path(out_dir)
    bbox_f = root / 'Anno' / 'list_bbox.txt'
    cat_f = root / 'Anno' / 'list_category_cloth.txt'
    img_cat_f = root / 'Anno' / 'list_category_img.txt'
    
    if not (bbox_f.exists() and cat_f.exists() and img_cat_f.exists()):
        print('Annotation files not found in ' + str(root_dir))
        return False
        
    cats = []
    with open(cat_f, 'r') as f:
        for l in f.read().strip().splitlines()[2:]:
            parts = l.strip().split()
            if parts: cats.append(parts[0].lower())
            
    img_map = {}
    with open(img_cat_f, 'r') as f:
        for l in f.read().strip().splitlines()[2:]:
            parts = l.strip().split()
            if len(parts) >= 2:
                idx = int(parts[1]) - 1
                if 0 <= idx < len(cats):
                    cid = DEEPFASHION_MAP.get(cats[idx], -1)
                    if cid >= 0: img_map[parts[0]] = cid
                    
    print(f'Found {len(img_map)} categorized images in DeepFashion.')
    count = 0
    with open(bbox_f, 'r') as f:
        for l in f.read().strip().splitlines()[2:]:
            if count >= max_samples: break
            parts = l.strip().split()
            if len(parts) >= 5:
                img_rel = parts[0]
                if img_rel not in img_map: continue
                src = root / img_rel
                if not src.exists(): continue
                x1, y1, x2, y2 = [int(v) for v in parts[1:5]]
                try:
                    with Image.open(src) as im: iw, ih = im.size
                    box = convert_bbox(x1, y1, x2, y2, iw, ih)
                    if not box: continue
                    cid = img_map[img_rel]
                    split = 'val' if (count % 7 == 0) else 'train'
                    img_dir = out / 'images' / split
                    lbl_dir = out / 'labels' / split
                    img_dir.mkdir(parents=True, exist_ok=True)
                    lbl_dir.mkdir(parents=True, exist_ok=True)
                    stem = f'df_{count:06d}'
                    shutil.copy2(src, img_dir / f'{stem}.jpg')
                    with open(lbl_dir / f'{stem}.txt', 'w') as lf:
                        lf.write(f'{cid} {box[0]:.6f} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f}\n')
                    count += 1
                    if count % 1000 == 0: print(f'Converted {count} samples...')
                except Exception: pass
    print(f'Done! Converted {count} samples to {out_dir}')
    return True

if __name__ == '__main__':
    if len(sys.argv) > 1: parse_deepfashion(sys.argv[1])
    else: print('Usage: python scripts/training/import_deepfashion.py <path_to_deepfashion_folder>')
