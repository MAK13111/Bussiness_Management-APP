"""
Configuration and Realistic Seed Data Pools for Demo Data Generation.
"""

import os
import sys

# Add parent directory to sys.path so we can import core.db if needed
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from core.db import PG_CONFIG, DATABASE_URL
except ImportError:
    PG_CONFIG = {
        "host": "localhost",
        "port": "5432",
        "dbname": "purchase_tracker",
        "user": "postgres",
        "password": "Password123",
    }
    DATABASE_URL = None

DEPARTMENTS = [
    "Menswear",
    "Womenswear",
    "Kidswear",
    "Footwear",
    "Accessories",
    "Fabrics",
    "Ethnic Wear",
    "Sports & Activewear",
    "Winter Collection",
    "Summer Collection",
]

CATEGORIES_ITEMS = {
    "Menswear": [
        "Slim Fit Cotton Shirt", "Formal Linen Trousers", "Denim Jeans Regular", "Polo Collar T-Shirt",
        "Casual Crew Neck Tee", "Tailored Blazer", "Chino Pants", "Bomber Jacket",
        "Kurta Pajama Set", "Hooded Sweatshirt", "Cargo Joggers", "Printed Hawaiian Shirt",
        "Formal Waistcoat", "Woolen Cardigan", "Athletic Track Pants"
    ],
    "Womenswear": [
        "Embroidered Anarkali Suit", "Floral Printed Kurti", "High-Waist Straight Jeans", "Silk Saree with Blouse",
        "Chiffon Maxi Dress", "A-Line Cotton Skirt", "Palazzo Trousers", "Casual Graphic Tee",
        "Formal Office Blazer", "Denim Jacket", "Georgette Dupatta", "Cropped Ribbed Top",
        "Partywear Evening Gown", "Churidar Leggings", "Kaftan Lounge Dress"
    ],
    "Kidswear": [
        "Kids Graphic T-Shirt", "Denim Shorts", "Party Frock", "Boys Dungaree Set",
        "Kids Cotton Pajama", "Cartoon Printed Hoody", "Girls Tutu Skirt", "Boys Formal Suit Set",
        "Infant Romper", "Kids Winter Jacket", "Pique Polo Tee", "Girls Floral Jumpsuit"
    ],
    "Footwear": [
        "Leather Oxford Shoes", "Sport Running Shoes", "Casual Canvas Sneakers", "Slip-On Loafers",
        "Traditional Mojari", "Ethnic Kolhapuri Chappal", "Comfort Walking Sandals", "High-Top Boots",
        "Stiletto Heels", "Comfort Ortho Slippers", "Waterproof Flip-Flops", "Leather Derby Shoes"
    ],
    "Accessories": [
        "Genuine Leather Belt", "Formal Silk Tie Set", "Classic Aviator Sunglasses", "Men Bifold Leather Wallet",
        "Women Clutch Handbag", "Cotton Handkerchiefs Pack", "Woolen Knitted Muffler", "Leather Laptop Bag",
        "Canvas Backpack", "Designer Brooch Pin", "Brass Cufflinks Set", "UV Protection Cap"
    ],
    "Fabrics": [
        "Pure Cotton Shirting Fabric", "Terry-Rayon Suiting Fabric", "Chanderi Silk Fabric", "Linen Blend Fabric",
        "Raw Silk Dress Material", "Polyester Viscose Fabric", "Jacquard Brocade Fabric", "Embroidered Georgette Material"
    ]
}

SIZES = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "28", "30", "32", "34", "36", "38", "40", "Free Size"]

UNITS = ["Pcs", "Mtrs", "Sets", "Pairs", "Dozens", "Boxes"]

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
    "Shaurya", "Atharva", "Kabir", "Aryan", "Advik", "Rudra", "Dhruv", "Rishabh", "Rohan", "Dev",
    "Diya", "Saanvi", "Ananya", "Aadhya", "Pari", "Chiara", "Riya", "Isha", "Anushka", "Myra",
    "Aditi", "Avani", "Ahana", "Tanvi", "Prisha", "Navya", "Meera", "Kavya", "Vanya", "Pooja",
    "Rajesh", "Vikram", "Sunil", "Manoj", "Suresh", "Ramesh", "Amit", "Deepak", "Alok", "Praveen",
    "Neha", "Priya", "Sneha", "Kiran", "Suman", "Shweta", "Anjali", "Sunita", "Anita", "Rekha"
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Mehta", "Shah", "Gupta", "Agarwal", "Singh", "Kumar", "Chopra",
    "Jain", "Bansal", "Kapoor", "Malhotra", "Reddy", "Rao", "Nair", "Iyer", "Mukherjee", "Chatterjee",
    "Bose", "Deshmukh", "Patil", "Kulkarni", "Joshi", "Gaikwad", "Shinde", "Yadav", "Tiwari", "Pandey"
]

BUSINESS_SUFFIXES = [
    "Enterprises", "Textiles", "Fabrics", "Apparels", "Fashions", "Garments", "Creations",
    "Trading Co.", "Wholesalers", "Retail Hub", "Collections", "Agencies", "International",
    "Trends", "Industries", "Boutique", "World", "Hub"
]

CITIES = [
    ("Mumbai", "Maharashtra", "400001", "27"),
    ("Surat", "Gujarat", "395001", "24"),
    ("Ahmedabad", "Gujarat", "380001", "24"),
    ("Jaipur", "Rajasthan", "302001", "08"),
    ("Delhi", "Delhi", "110001", "07"),
    ("Kolkata", "West Bengal", "700001", "19"),
    ("Bengaluru", "Karnataka", "560001", "29"),
    ("Chennai", "Tamil Nadu", "600001", "33"),
    ("Ludhiana", "Punjab", "141001", "03"),
    ("Indore", "Madhya Pradesh", "452001", "23"),
    ("Kanpur", "Uttar Pradesh", "208001", "09"),
    ("Hyderabad", "Telangana", "500001", "36"),
    ("Pune", "Maharashtra", "411001", "27"),
    ("Tirupur", "Tamil Nadu", "641601", "33"),
]

STREETS = [
    "MG Road, Cloth Market", "Linking Road, Commercial Complex", "Gandhi Nagar Market",
    "Ring Road Textile Market", "Chandni Chowk", "Bada Bazar, Textile Sector",
    "Station Road, Wholesale Market", "Commercial Street", "Industrial Area Phase II",
    "Ring Road, APMC Market", "Chowk Bazar", "Fashion Street Lane"
]

RETURN_REASONS = [
    "Size mismatch reported by customer",
    "Color variance compared to sample",
    "Minor stitching defect on left sleeve",
    "Fabric quality not as per specification",
    "Customer changed preference",
    "Wrong item shipped in consignment",
    "Exchange requested for alternative design",
    "Damaged packaging upon arrival",
    "Duplicate purchase returned",
    "Transit wear and tear noted"
]

PAYMENT_MODES = ["Cash", "Online", "NEFT/RTGS", "UPI", "Cheque", "Card"]

STATUS_MODES = ["Cash", "Credit", "Partial", "Paid"]

NARRATIONS = [
    "Being goods purchased on credit terms with 30-day payment schedule as per invoice terms.",
    "Being sales made against counter bill with payment received in full through mixed modes.",
    "Being payment settled against pending balance via RTGS electronic bank transfer.",
    "Being adjustment voucher passed for return credit note and stock reversal.",
    "Being bulk seasonal procurement under trade discount promotion program.",
    "Being retail counter sales transaction with loyalty discount applied.",
    "Being inventory stock receipt verified at central warehouse quality check terminal."
]
