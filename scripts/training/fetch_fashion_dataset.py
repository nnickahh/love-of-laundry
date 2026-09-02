import os, sys
from pathlib import Path
from PIL import Image
from datasets import load_dataset

CLASS_MAP = {
    'Tshirts': 0, 'Shirts': 0, 'Tops': 0, 'Tunics': 0,
    'Jackets': 1, 'Coats': 1, 'Blazers': 1, 'Rain Jacket': 1, 'Nehru Jackets': 1,
    'Jeans': 2, 'Trousers': 2, 'Track Pants': 2, 'Leggings': 2, 'Capris': 2, 'Jeggings': 2, 'Chinos': 2,
    'Shorts': 13, 'Boxers': 13, 'Swimwear': 13,
    'Dresses': 4, 'Jumpsuit': 4, 'Rompers': 4,
    'Skirts': 14
}

def build_dataset(max_per_class=400, out_dir='dataset/deepfashion_converted'):
    out_root = Path(out_dir)
    for split in ['train', 'val']:
        (out_root / 'images' / split).mkdir(parents=True, exist_ok=True)
        (out_root / 'labels' / split).mkdir(parents=True, exist_ok=True)
        
    print('Streaming fashion dataset from HuggingFace...')
    ds = load_dataset('ashraq/fashion-product-images-small', split='train')
    print(f'Total records available: {len(ds)}')
    
    class_counts = {c: 0 for c in range(15)}
    total_saved = 0
    
    for idx, item in enumerate(ds):
        art_type = item.get('articleType', '')
        if art_type not in CLASS_MAP:
            continue
            
        cid = CLASS_MAP[art_type]
        if class_counts[cid] >= max_per_class:
            continue
            
        img = item.get('image')
        if img is None:
            continue
            
        w, h = img.size
        # Bounding box around the central garment
        xc, yc, bw, bh = 0.50, 0.50, 0.85, 0.88
        
        split = 'val' if (class_counts[cid] % 6 == 0) else 'train'
        stem = f'fashion_{cid}_{class_counts[cid]:05d}'
        
        img_p = out_root / 'images' / split / f'{stem}.jpg'
        lbl_p = out_root / 'labels' / split / f'{stem}.txt'
        
        try:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(img_p, 'JPEG', quality=95)
            with open(lbl_p, 'w') as lf:
                lf.write(f'{cid} {xc:.4f} {yc:.4f} {bw:.4f} {bh:.4f}\n')
                
            class_counts[cid] += 1
            total_saved += 1
            if total_saved % 500 == 0:
                print(f'Saved {total_saved} images across categories...')
        except Exception as e:
            pass
            
    print('='*60)
    print(f'Fashion Dataset Ingestion Complete! Saved {total_saved} images to {out_dir}:')
    print(f'  - T-Shirts / Tops: {class_counts[0]}')
    print(f'  - Jackets:         {class_counts[1]}')
    print(f'  - Pants / Jeans:   {class_counts[2]}')
    print(f'  - Shorts:          {class_counts[13]}')
    print(f'  - Dresses / Skirts:{class_counts[4] + class_counts[14]}')
    print('='*60)

if __name__ == '__main__':
    build_dataset()
