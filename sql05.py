import streamlit as st
import pymysql
import pandas as pd
import plotly.express as px
from faker import Faker
import random
from datetime import datetime, timedelta
import hashlib
import config

# -------------------------- 1. 数据库配置与连接 --------------------------
def get_db_connection():
    try:
        conn = pymysql.connect(
            host=config.MYSQL_HOST,  
            user=config.MYSQL_USER,       
            password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DB,  # 用配置文件的数据库名，不再硬编码
            charset="utf8mb4"
        )
        return conn
    except Exception as e:
        st.error(f"数据库连接失败：{str(e)}")
        return None

# 初始化数据库（创建表、触发器、存储过程）
def init_database():
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()

    # -------------------------- 1.1 创建表及参照完整性约束 --------------------------
    # 用户表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INT PRIMARY KEY AUTO_INCREMENT,
        username VARCHAR(50) UNIQUE NOT NULL,
        password VARCHAR(100) NOT NULL,
        role ENUM('user', 'merchant', 'admin') NOT NULL DEFAULT 'user',
        phone VARCHAR(20),
        address VARCHAR(255),
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # 商家表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS merchants (
        merchant_id INT PRIMARY KEY AUTO_INCREMENT,
        user_id INT UNIQUE NOT NULL,
        merchant_name VARCHAR(100) NOT NULL,
        business_license VARCHAR(100),
        contact_phone VARCHAR(20),
        rating FLOAT DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # 商品表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        product_id INT PRIMARY KEY AUTO_INCREMENT,
        merchant_id INT NOT NULL,
        product_name VARCHAR(100) NOT NULL,
        price DECIMAL(10,2) NOT NULL,
        stock INT NOT NULL DEFAULT 0,
        category VARCHAR(50),
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (merchant_id) REFERENCES merchants(merchant_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # 订单表（交易记录）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id INT PRIMARY KEY AUTO_INCREMENT,
        user_id INT NOT NULL,
        product_id INT NOT NULL,
        order_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        status ENUM('pending', 'paid', 'shipped', 'completed', 'cancelled') NOT NULL DEFAULT 'pending',
        total_amount DECIMAL(10,2) NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # 物流表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logistics (
        logistics_id INT PRIMARY KEY AUTO_INCREMENT,
        order_id INT UNIQUE NOT NULL,
        logistics_company VARCHAR(50),
        tracking_number VARCHAR(50),
        status ENUM('pending', 'in_transit', 'delivered') NOT NULL DEFAULT 'pending',
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # 评价表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        review_id INT PRIMARY KEY AUTO_INCREMENT,
        order_id INT UNIQUE NOT NULL,
        rating INT CHECK (rating BETWEEN 1 AND 5),
        comment TEXT,
        review_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # 登录记录表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS login_records (
        record_id INT PRIMARY KEY AUTO_INCREMENT,
        user_id INT NOT NULL,
        login_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        ip_address VARCHAR(50),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # 客服记录表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customer_service (
        cs_id INT PRIMARY KEY AUTO_INCREMENT,
        user_id INT NOT NULL,
        merchant_id INT,
        content TEXT NOT NULL,
        reply TEXT,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        reply_time DATETIME,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (merchant_id) REFERENCES merchants(merchant_id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # -------------------------- 1.2 创建触发器 --------------------------
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS update_logistics_on_order_complete
    AFTER UPDATE ON orders
    FOR EACH ROW
    BEGIN
        IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
            UPDATE logistics 
            SET status = 'delivered', update_time = CURRENT_TIMESTAMP 
            WHERE order_id = NEW.order_id;
        END IF;
    END;
    """)

    # -------------------------- 1.3 创建存储过程 --------------------------
    # 存储过程1：查询各商品的购买人数及好评率
    cursor.execute("""
    CREATE PROCEDURE IF NOT EXISTS get_product_purchase_stats()
    BEGIN
        SELECT 
            p.product_id,
            p.product_name,
            COUNT(DISTINCT o.user_id) AS purchase_count,
            IFNULL(AVG(r.rating), 0) AS avg_rating,
            CONCAT(ROUND(IFNULL(SUM(CASE WHEN r.rating >= 4 THEN 1 ELSE 0 END)/COUNT(r.rating)*100, 0), 2), '%') AS positive_rate
        FROM products p
        LEFT JOIN orders o ON p.product_id = o.product_id AND o.status = 'completed'
        LEFT JOIN reviews r ON o.order_id = r.order_id
        GROUP BY p.product_id, p.product_name;
    END;
    """)

    # 存储过程2：查询指定商品的购买趋势（按周统计）
    cursor.execute("""
    CREATE PROCEDURE IF NOT EXISTS get_product_purchase_trend(IN prod_id INT)
    BEGIN
        SELECT 
            DATE_FORMAT(o.order_time, '%Y-%m-%d') AS order_date,
            COUNT(o.order_id) AS daily_purchase
        FROM orders o
        WHERE o.product_id = prod_id AND o.status IN ('paid', 'completed')
        GROUP BY DATE_FORMAT(o.order_time, '%Y-%m-%d')
        ORDER BY order_date;
    END;
    """)

    conn.commit()
    cursor.close()
    conn.close()
    st.success("数据库初始化完成！")

# -------------------------- 2. 生成随机测试数据 --------------------------
def generate_test_data():
    fake = Faker("zh_CN")
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()

    # 清空现有数据
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
    for table in ['login_records', 'customer_service', 'reviews', 'logistics', 'orders', 'products', 'merchants', 'users']:
        cursor.execute(f"TRUNCATE TABLE {table};")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

    # 生成管理员账号
    admin_pwd = hashlib.md5("admin123".encode()).hexdigest()
    cursor.execute("INSERT INTO users (username, password, role) VALUES ('admin', %s, 'admin')", (admin_pwd,))

    # 生成商家用户（唯一用户名）
    merchants_data = []
    used_usernames = {'admin'}
    for _ in range(10):
        while True:
            base_name = fake.user_name()
            username = f"{base_name}_{random.randint(1000, 9999)}"
            if username not in used_usernames:
                used_usernames.add(username)
                break
        pwd = hashlib.md5(fake.password().encode()).hexdigest()
        cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, 'merchant')", (username, pwd))
        user_id = cursor.lastrowid
        merchant_name = fake.company()
        license = fake.ssn()
        phone = fake.phone_number()
        rating = round(random.uniform(3.0, 5.0), 1)
        merchants_data.append((user_id, merchant_name, license, phone, rating))
    cursor.executemany("INSERT INTO merchants (user_id, merchant_name, business_license, contact_phone, rating) VALUES (%s, %s, %s, %s, %s)", merchants_data)

    # 生成普通用户（唯一用户名）
    users_data = []
    for _ in range(50):
        while True:
            base_name = fake.user_name()
            username = f"{base_name}_{random.randint(1000, 9999)}"
            if username not in used_usernames:
                used_usernames.add(username)
                break
        pwd = hashlib.md5(fake.password().encode()).hexdigest()
        role = 'user'
        phone = fake.phone_number()
        address = fake.address()
        users_data.append((username, pwd, role, phone, address))
    cursor.executemany("INSERT INTO users (username, password, role, phone, address) VALUES (%s, %s, %s, %s, %s)", users_data)

    # 生成商品
    products_data = []
    category_products = {
        "电子产品": ["智能手机（Pro版）", "无线蓝牙耳机", "轻薄笔记本电脑", "平板电脑（Air）", "智能手表（运动款）",
                    "机械键盘（青轴）", "电竞鼠标", "27寸4K显示器", "移动固态硬盘（1T）", "快充充电器（65W）"],
        "服装": ["纯棉圆领T恤（白色）", "修身牛仔裤（蓝色）", "休闲连帽外套（黑色）", "透气运动鞋（42码）", "雪纺连衣裙（M码）",
                "羊毛针织衫（米色）", "工装短裤（XL）", "帆布鞋（低帮）", "羽绒服（中长款）", "冰丝防晒衣（灰色）"],
        "食品": ["原味薯片（100g）", "黑巧克力（80%可可）", "碳酸饮料（500ml）", "夹心饼干（牛奶味）", "混合坚果（250g）",
                "速溶咖啡（特浓）", "方便面（红烧牛肉）", "火腿肠（优级）", "酸奶（原味）", "每日坚果（30包）"],
        "家居": ["纯棉抱枕（45*45cm）", "LED护眼台灯", "全棉床单（1.8m）", "塑料收纳盒（3个装）", "短绒地毯（1.6*2m）",
                "厨房置物架", "卫生间收纳柜", "防滑地垫", "纯棉毛巾（2条装）", "玻璃水杯（300ml）"],
        "美妆": ["哑光口红（正红色）", "补水面膜（10片）", "持妆粉底液（自然色）", "防水睫毛膏", "保湿护手霜（50g）",
                "卸妆油（150ml）", "散粉（定妆）", "眉笔（深棕色）", "腮红（蜜桃色）", "隔离霜（提亮款）"]
    }
    categories = list(category_products.keys())
    for cat in categories:
        for idx in range(20):
            merchant_id = random.randint(1, 10)
            prod_base_name = category_products[cat][idx % len(category_products[cat])]
            product_name = f"{prod_base_name}（{idx+1}）"
            price = round(random.uniform(10, 1000), 2)
            stock = random.randint(500, 2000)
            products_data.append((merchant_id, product_name, price, stock, cat))
    cursor.executemany("INSERT INTO products (merchant_id, product_name, price, stock, category) VALUES (%s, %s, %s, %s, %s)", products_data)

    # 生成订单
    cursor.execute("SELECT product_id FROM products")
    all_product_ids = [row[0] for row in cursor.fetchall()]
    start_date = datetime.now() - timedelta(days=180)
    end_date = datetime.now()
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    orders_data = []
    status_list = ['paid', 'completed']
    # 每个商品至少50个订单
    for product_id in all_product_ids:
        for _ in range(50):
            user_id = random.randint(12, 61)
            random_date = random.choice(date_list)
            order_time = fake.date_time_between(start_date=random_date, end_date=random_date + timedelta(days=1))
            status = random.choice(status_list)
            total_amount = round(random.uniform(10, 2000), 2)
            orders_data.append((user_id, product_id, order_time, status, total_amount))
    # 额外1000个随机订单
    for _ in range(1000):
        product_id = random.choice(all_product_ids)
        user_id = random.randint(12, 61)
        random_date = random.choice(date_list)
        order_time = fake.date_time_between(start_date=random_date, end_date=random_date + timedelta(days=1))
        status = random.choice(status_list)
        total_amount = round(random.uniform(10, 2000), 2)
        orders_data.append((user_id, product_id, order_time, status, total_amount))
    cursor.executemany("INSERT INTO orders (user_id, product_id, order_time, status, total_amount) VALUES (%s, %s, %s, %s, %s)", orders_data)

    # 物流记录
    logistics_data = []
    logistics_companies = ["顺丰", "圆通", "中通", "韵达", "申通"]
    for order_id in range(1, len(orders_data)+1):
        company = random.choice(logistics_companies)
        tracking = fake.random_number(digits=12)
        logistics_status = random.choice(['in_transit', 'delivered'])
        logistics_data.append((order_id, company, tracking, logistics_status))
    cursor.executemany("INSERT INTO logistics (order_id, logistics_company, tracking_number, status) VALUES (%s, %s, %s, %s)", logistics_data)

    # 评价
    reviews_data = []
    for order_id in random.sample(range(1, len(orders_data)+1), 300):
        rating = random.randint(4, 5)
        comment = fake.sentence()
        review_time = fake.date_time_between(start_date=start_date, end_date="now")
        reviews_data.append((order_id, rating, comment, review_time))
    cursor.executemany("INSERT INTO reviews (order_id, rating, comment, review_time) VALUES (%s, %s, %s, %s)", reviews_data)

        # 登录记录（300个，时间分散在最近6个月）
    login_records_data = []
    for _ in range(300):
        user_id = random.randint(1, 61)
        # 时间范围改为“最近6个月”，避免集中在同一时间段
        login_time = fake.date_time_between(start_date="-6months", end_date="now")
        ip = fake.ipv4()
        login_records_data.append((user_id, login_time, ip))
    cursor.executemany("INSERT INTO login_records (user_id, login_time, ip_address) VALUES (%s, %s, %s)", login_records_data)

    # 客服记录
    cs_data = []
    for _ in range(50):
        user_id = random.randint(12, 61)
        merchant_id = random.randint(1, 10)
        content = fake.paragraph()
        reply = fake.paragraph() if random.random() > 0.3 else None
        create_time = fake.date_time_between(start_date="-1months", end_date="now")
        reply_time = fake.date_time_between(start_date=create_time, end_date="now") if reply else None
        cs_data.append((user_id, merchant_id, content, reply, create_time, reply_time))
    cursor.executemany("INSERT INTO customer_service (user_id, merchant_id, content, reply, create_time, reply_time) VALUES (%s, %s, %s, %s, %s, %s)", cs_data)

    conn.commit()
    cursor.close()
    conn.close()
    st.success("测试数据生成完成！")

# -------------------------- 3. 登录鉴权逻辑 --------------------------
def hash_password(password):
    """密码加密（MD5）"""
    return hashlib.md5(password.encode()).hexdigest()

def authenticate(username, password, role):
    """验证登录信息"""
    conn = get_db_connection()
    if not conn:
        return False, None
    cursor = conn.cursor()
    hashed_pwd = hash_password(password)
    cursor.execute("SELECT user_id, username FROM users WHERE username = %s AND password = %s AND role = %s", (username, hashed_pwd, role))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if user:
        # 记录登录日志
        log_login(user[0])
        return True, user[0]
    return False, None

def log_login(user_id):
    """记录登录日志"""
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    fake = Faker()
    ip = fake.ipv4()
    cursor.execute("INSERT INTO login_records (user_id, ip_address) VALUES (%s, %s)", (user_id, ip))
    conn.commit()
    cursor.close()
    conn.close()

# -------------------------- 4. 通用CRUD函数 --------------------------
# -------------------------- 4.1 用户管理CRUD --------------------------
def get_users(filter_type="all", filter_value=None):
    """查询用户：all/by_id/by_username/by_role"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    query = "SELECT user_id, username, role, phone, address, create_time FROM users"
    params = []
    if filter_type == "by_id" and filter_value:
        query += " WHERE user_id = %s"
        params = [filter_value]
    elif filter_type == "by_username" and filter_value:
        query += " WHERE username LIKE %s"
        params = [f"%{filter_value}%"]
    elif filter_type == "by_role" and filter_value:
        query += " WHERE role = %s"
        params = [filter_value]
    query += " ORDER BY user_id ASC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def add_user(username, password, role, phone="", address=""):
    """新增用户"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        hashed_pwd = hash_password(password)
        cursor.execute(
            "INSERT INTO users (username, password, role, phone, address) VALUES (%s, %s, %s, %s, %s)",
            (username, hashed_pwd, role, phone, address)
        )
        conn.commit()
        return True, "用户新增成功"
    except pymysql.IntegrityError:
        return False, "用户名已存在"
    except Exception as e:
        return False, f"新增失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

def update_user(user_id, username=None, password=None, role=None, phone=None, address=None):
    """修改用户（新增用户名、密码修改支持）"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        updates = []
        params = []
        # 处理用户名
        if username:
            updates.append("username = %s")
            params.append(username)
        # 处理密码（自动加密）
        if password:
            hashed_pwd = hash_password(password)  # 调用加密函数
            updates.append("password = %s")
            params.append(hashed_pwd)
        # 处理角色
        if role:
            updates.append("role = %s")
            params.append(role)
        # 处理手机号
        if phone:
            updates.append("phone = %s")
            params.append(phone)
        # 处理地址
        if address:
            updates.append("address = %s")
            params.append(address)
        
        if not updates:
            return False, "未填写任何修改内容"
        
        query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s"
        params.append(user_id)
        cursor.execute(query, params)
        conn.commit()
        
        if cursor.rowcount > 0:
            return True, "用户修改成功"
        else:
            return False, "未找到该用户"
    except pymysql.IntegrityError:
        return False, "用户名已存在（用户名需唯一）"
    except Exception as e:
        return False, f"修改失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

def delete_user(user_id):
    """删除用户"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()
        if cursor.rowcount > 0:
            return True, "用户删除成功"
        else:
            return False, "未找到该用户"
    except pymysql.IntegrityError:
        return False, "该用户关联了其他数据，无法删除"
    except Exception as e:
        return False, f"删除失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

# -------------------------- 4.2 商家管理CRUD --------------------------
def get_merchants(filter_type="all", filter_value=None):
    """查询商家：all/by_id/by_name/by_rating"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    query = """
    SELECT m.merchant_id, m.user_id, u.username, m.merchant_name, 
           m.business_license, m.contact_phone, m.rating
    FROM merchants m
    LEFT JOIN users u ON m.user_id = u.user_id
    """
    params = []
    if filter_type == "by_id" and filter_value:
        query += " WHERE m.merchant_id = %s"
        params = [filter_value]
    elif filter_type == "by_name" and filter_value:
        query += " WHERE m.merchant_name LIKE %s"
        params = [f"%{filter_value}%"]
    elif filter_type == "by_rating" and filter_value:
        query += " WHERE m.rating >= %s"
        params = [filter_value]
    query += " ORDER BY m.merchant_id ASC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def add_merchant(user_id, merchant_name, business_license, contact_phone, rating):
    """新增商家"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO merchants (user_id, merchant_name, business_license, contact_phone, rating) VALUES (%s, %s, %s, %s, %s)",
            (user_id, merchant_name, business_license, contact_phone, rating)
        )
        conn.commit()
        return True, "商家新增成功"
    except pymysql.IntegrityError:
        return False, "该用户已关联商家/用户ID不存在"
    except Exception as e:
        return False, f"新增失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

def update_merchant(merchant_id, merchant_name=None, business_license=None, contact_phone=None, rating=None):
    """修改商家"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        updates = []
        params = []
        if merchant_name:
            updates.append("merchant_name = %s")
            params.append(merchant_name)
        if business_license:
            updates.append("business_license = %s")
            params.append(business_license)
        if contact_phone:
            updates.append("contact_phone = %s")
            params.append(contact_phone)
        if rating:
            updates.append("rating = %s")
            params.append(rating)
        if not updates:
            return False, "未填写任何修改内容"
        
        query = f"UPDATE merchants SET {', '.join(updates)} WHERE merchant_id = %s"
        params.append(merchant_id)
        cursor.execute(query, params)
        conn.commit()
        if cursor.rowcount > 0:
            return True, "商家修改成功"
        else:
            return False, "未找到该商家"
    except Exception as e:
        return False, f"修改失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

def delete_merchant(merchant_id):
    """删除商家"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM merchants WHERE merchant_id = %s", (merchant_id,))
        conn.commit()
        if cursor.rowcount > 0:
            return True, "商家删除成功"
        else:
            return False, "未找到该商家"
    except pymysql.IntegrityError:
        return False, "该商家关联了商品/订单，无法删除"
    except Exception as e:
        return False, f"删除失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

# -------------------------- 4.3 商品管理CRUD --------------------------
def get_products(filter_type="all", filter_value=None, merchant_id=None):
    """查询商品：all/by_id/by_name/by_category/by_merchant"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    query = """
    SELECT p.product_id, p.merchant_id, m.merchant_name, p.product_name, 
           p.price, p.stock, p.category, p.create_time
    FROM products p
    LEFT JOIN merchants m ON p.merchant_id = m.merchant_id
    """
    params = []
    if filter_type == "by_id" and filter_value:
        query += " WHERE p.product_id = %s"
        params = [filter_value]
    elif filter_type == "by_name" and filter_value:
        query += " WHERE p.product_name LIKE %s"
        params = [f"%{filter_value}%"]
    elif filter_type == "by_category" and filter_value:
        query += " WHERE p.category = %s"
        params = [filter_value]
    elif filter_type == "by_merchant" and filter_value:
        query += " WHERE p.merchant_id = %s"
        params = [filter_value]
    if merchant_id:
        if "WHERE" in query:
            query += " AND p.merchant_id = %s"
        else:
            query += " WHERE p.merchant_id = %s"
        params.append(merchant_id)
    query += " ORDER BY p.product_id ASC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def add_product(merchant_id, product_name, price, stock, category):
    """新增商品"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO products (merchant_id, product_name, price, stock, category) VALUES (%s, %s, %s, %s, %s)",
            (merchant_id, product_name, price, stock, category)
        )
        conn.commit()
        return True, "商品新增成功"
    except pymysql.IntegrityError:
        return False, "商家ID不存在"
    except Exception as e:
        return False, f"新增失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

def update_product(product_id, product_name=None, price=None, stock=None, category=None):
    """修改商品"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        updates = []
        params = []
        if product_name:
            updates.append("product_name = %s")
            params.append(product_name)
        if price:
            updates.append("price = %s")
            params.append(price)
        if stock:
            updates.append("stock = %s")
            params.append(stock)
        if category:
            updates.append("category = %s")
            params.append(category)
        if not updates:
            return False, "未填写任何修改内容"
        
        query = f"UPDATE products SET {', '.join(updates)} WHERE product_id = %s"
        params.append(product_id)
        cursor.execute(query, params)
        conn.commit()
        if cursor.rowcount > 0:
            return True, "商品修改成功"
        else:
            return False, "未找到该商品"
    except Exception as e:
        return False, f"修改失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

def delete_product(product_id):
    """删除商品"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
        conn.commit()
        if cursor.rowcount > 0:
            return True, "商品删除成功"
        else:
            return False, "未找到该商品"
    except pymysql.IntegrityError:
        return False, "该商品关联了订单，无法删除"
    except Exception as e:
        return False, f"删除失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

# -------------------------- 4.4 订单管理CRUD --------------------------
def get_orders(filter_type="all", filter_value=None, user_id=None):
    """查询订单：all/by_id/by_user/by_status/by_date"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    query = """
    SELECT o.order_id, o.user_id, u.username, o.product_id, p.product_name,
           o.order_time, o.status, o.total_amount
    FROM orders o
    LEFT JOIN users u ON o.user_id = u.user_id
    LEFT JOIN products p ON o.product_id = p.product_id
    """
    params = []
    if filter_type == "by_id" and filter_value:
        query += " WHERE o.order_id = %s"
        params = [filter_value]
    elif filter_type == "by_user" and filter_value:
        query += " WHERE o.user_id = %s"
        params = [filter_value]
    elif filter_type == "by_status" and filter_value:
        query += " WHERE o.status = %s"
        params = [filter_value]
    elif filter_type == "by_date" and filter_value:
        query += " WHERE DATE(o.order_time) = %s"
        params = [filter_value]
    if user_id:
        if "WHERE" in query:
            query += " AND o.user_id = %s"
        else:
            query += " WHERE o.user_id = %s"
        params.append(user_id)
    query += " ORDER BY o.order_time DESC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def update_order_status(order_id, new_status):
    """修改订单状态"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE orders SET status = %s WHERE order_id = %s",
            (new_status, order_id)
        )
        conn.commit()
        if cursor.rowcount > 0:
            return True, "订单状态修改成功"
        else:
            return False, "未找到该订单"
    except Exception as e:
        return False, f"修改失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

# -------------------------- 4.5 登录记录查询 --------------------------
def get_login_records(filter_type="all", filter_value=None, user_id=None):
    """查询登录记录：all/by_user/by_username/by_date"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    query = """
    SELECT lr.record_id, lr.user_id, u.username, lr.login_time, lr.ip_address
    FROM login_records lr
    LEFT JOIN users u ON lr.user_id = u.user_id
    """
    params = []
    if filter_type == "by_user" and filter_value:
        query += " WHERE lr.user_id = %s"
        params = [filter_value]
    elif filter_type == "by_username" and filter_value:
        query += " WHERE u.username LIKE %s"
        params = [f"%{filter_value}%"]
    elif filter_type == "by_date" and filter_value:
        query += " WHERE DATE(lr.login_time) = %s"
        params = [filter_value]
    if user_id:
        if "WHERE" in query:
            query += " AND lr.user_id = %s"
        else:
            query += " WHERE lr.user_id = %s"
        params.append(user_id)
    query += " ORDER BY lr.login_time DESC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

# -------------------------- 4.6 客服记录CRUD --------------------------
def get_cs_records(filter_type="all", filter_value=None, is_replied=None):
    """查询客服记录：all/by_id/by_user/by_merchant/by_reply_status"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    query = """
    SELECT cs.cs_id, cs.user_id, u.username, cs.merchant_id, m.merchant_name,
           cs.content, cs.reply, cs.create_time, cs.reply_time
    FROM customer_service cs
    LEFT JOIN users u ON cs.user_id = u.user_id
    LEFT JOIN merchants m ON cs.merchant_id = m.merchant_id
    """
    params = []
    if filter_type == "by_id" and filter_value:
        query += " WHERE cs.cs_id = %s"
        params = [filter_value]
    elif filter_type == "by_user" and filter_value:
        query += " WHERE cs.user_id = %s"
        params = [filter_value]
    elif filter_type == "by_merchant" and filter_value:
        query += " WHERE cs.merchant_id = %s"
        params = [filter_value]
    if is_replied is not None:
        if "WHERE" in query:
            query += " AND cs.reply IS " + ("NOT NULL" if is_replied else "NULL")
        else:
            query += " WHERE cs.reply IS " + ("NOT NULL" if is_replied else "NULL")
    query += " ORDER BY cs.create_time DESC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def reply_cs_record(cs_id, reply_content):
    """回复客服记录"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE customer_service SET reply = %s, reply_time = CURRENT_TIMESTAMP WHERE cs_id = %s",
            (reply_content, cs_id)
        )
        conn.commit()
        if cursor.rowcount > 0:
            return True, "回复成功"
        else:
            return False, "未找到该客服记录"
    except Exception as e:
        return False, f"回复失败：{str(e)}"
    finally:
        cursor.close()
        conn.close()

# -------------------------- 4.7 数据统计函数 --------------------------
def get_product_stats():
    """获取商品购买统计"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    cursor = conn.cursor()
    cursor.callproc("get_product_purchase_stats")
    stats = cursor.fetchall()
    df = pd.DataFrame(stats, columns=["商品ID", "商品名称", "购买人数", "平均评分", "好评率"])
    cursor.close()
    conn.close()
    return df

def get_product_trend(product_id):
    """获取商品购买趋势"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    cursor = conn.cursor()
    cursor.callproc("get_product_purchase_trend", [product_id])
    trend = cursor.fetchall()
    df = pd.DataFrame(trend, columns=["日期", "日购买量"])
    df["日期"] = pd.to_datetime(df["日期"])
    cursor.close()
    conn.close()
    return df

def get_top_merchants():
    """获取优质商家TOP5"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    df = pd.read_sql("SELECT merchant_id, merchant_name, rating FROM merchants ORDER BY rating DESC LIMIT 5", conn)
    conn.close()
    return df

# -------------------------- 5. Streamlit前端UI --------------------------
def main():
    st.set_page_config(page_title="电商平台管理系统", page_icon="🛒", layout="wide")
    st.title("🛒 电商平台管理系统")

    # 初始化Session State
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    if "role" not in st.session_state:
        st.session_state.role = None

    # 未登录时显示登录界面
    if not st.session_state.logged_in:
        st.subheader("🔐 系统登录")
        with st.form("login_form"):
            col1, col2 = st.columns(2)
            with col1:
                username = st.text_input("账号", placeholder="请输入用户名")
                password = st.text_input("密码", type="password", placeholder="请输入密码")
            with col2:
                role = st.selectbox("身份", ["user", "merchant", "admin"], format_func=lambda x: {"user":"普通用户", "merchant":"商家", "admin":"管理员"}[x])
            submit_btn = st.form_submit_button("登录", type="primary")

            if submit_btn:
                if not username or not password:
                    st.warning("账号/密码不能为空！")
                else:
                    success, user_id = authenticate(username, password, role)
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.user_id = user_id
                        st.session_state.role = role
                        st.success(f"{role}登录成功！")
                        st.rerun()
                    else:
                        st.error("账号/密码/身份不匹配！")

        # 数据库初始化按钮
        with st.expander("⚙️ 系统初始化（首次使用请点击）"):
            col1, col2 = st.columns(2)
            with col1:
                if st.button("初始化数据库", type="secondary"):
                    init_database()
            with col2:
                if st.button("生成测试数据", type="secondary"):
                    generate_test_data()

    # 已登录时显示功能界面
    else:
        # 侧边栏导航
        st.sidebar.title(f"当前身份：{st.session_state.role}")
        st.sidebar.divider()
        menu = ["首页", "数据统计", "登录记录", "交易记录"]
        if st.session_state.role == "admin":
            menu.extend(["用户管理", "商家管理", "商品管理", "客服管理"])
        elif st.session_state.role == "merchant":
            menu.extend(["我的商品", "我的订单", "评价管理"])
        elif st.session_state.role == "user":
            menu.extend(["我的订单", "我的评价", "客服中心", "商家推荐"])
        menu.append("退出登录")
        choice = st.sidebar.selectbox("功能菜单", menu)

        # 退出登录
        if choice == "退出登录":
            st.session_state.logged_in = False
            st.session_state.user_id = None
            st.session_state.role = None
            st.rerun()

        # 首页
        elif choice == "首页":
            st.subheader("📊 系统概览")
            conn = get_db_connection()
            if conn:
                # 核心数据卡片
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    user_count = pd.read_sql("SELECT COUNT(*) FROM users", conn).iloc[0,0]
                    st.metric("总用户数", user_count)
                with col2:
                    product_count = pd.read_sql("SELECT COUNT(*) FROM products", conn).iloc[0,0]
                    st.metric("商品总数", product_count)
                with col3:
                    order_count = pd.read_sql("SELECT COUNT(*) FROM orders", conn).iloc[0,0]
                    st.metric("订单总数", order_count)
                with col4:
                    complete_order = pd.read_sql("SELECT COUNT(*) FROM orders WHERE status='completed'", conn).iloc[0,0]
                    st.metric("已完成订单", complete_order)
        
                # 可视化图表区域
                st.divider()
                st.write("### 数据可视化分析")
        
                # 商品分类占比
                product_category_df = pd.read_sql(
                    "SELECT category, COUNT(*) AS product_num FROM products GROUP BY category", 
                    conn
                )
                fig_category = px.pie(
                    product_category_df,
                    values="product_num",
                    names="category",
                    title="商品分类占比",
                    hole=0.4
                )
                fig_category.update_traces(textposition="inside", textinfo="percent+label")
        
                # 订单状态分布
                order_status_df = pd.read_sql(
                    "SELECT status, COUNT(*) AS order_num FROM orders GROUP BY status", 
                    conn
                )
                status_cn_map = {
                    "pending": "待付款", "paid": "已付款", "shipped": "已发货",
                    "completed": "已完成", "cancelled": "已取消"
                }
                order_status_df["status_cn"] = order_status_df["status"].map(status_cn_map)
                fig_order_status = px.bar(
                    order_status_df,
                    x="status_cn", y="order_num",
                    title="订单状态分布", color="status_cn", text="order_num"
                )
                fig_order_status.update_layout(xaxis_title="订单状态", yaxis_title="订单数量")
        
                # 30天订单趋势
                start_date_30 = datetime.now() - timedelta(days=30)
                order_trend_df = pd.read_sql(
                    """
                    SELECT DATE(order_time) AS order_date, COUNT(*) AS daily_orders
                    FROM orders WHERE order_time >= %s
                    GROUP BY DATE(order_time) ORDER BY order_date
                    """,
                    conn, params=(start_date_30,)
                )
                order_trend_df["order_date"] = pd.to_datetime(order_trend_df["order_date"])
                fig_order_trend = px.line(
                    order_trend_df, x="order_date", y="daily_orders",
                    title="最近30天订单数量趋势", markers=True
                )
                fig_order_trend.update_layout(xaxis_title="日期", yaxis_title="每日订单数")
                fig_order_trend.update_xaxes(tickformat="%m-%d")
        
                # 图表排版
                col_a, col_b = st.columns(2)
                with col_a:
                    st.plotly_chart(fig_category, use_container_width=True)
                with col_b:
                    st.plotly_chart(fig_order_status, use_container_width=True)
                st.plotly_chart(fig_order_trend, use_container_width=True)
        
                conn.close()

        # 登录记录
        elif choice == "登录记录":
            if st.session_state.role == "admin":
                st.subheader("🔑 登录记录查询")
                
                # 筛选条件
                st.write("### 筛选条件")
                col1, col2, col3 = st.columns(3)
                with col1:
                    filter_type = st.selectbox("筛选类型", ["全部", "按用户ID", "按用户名", "按日期"])
                with col2:
                    filter_value = st.text_input("筛选值", placeholder="用户ID/用户名/日期(YYYY-MM-DD)")
                with col3:
                    query_btn = st.button("查询", type="primary")
                
                # 显示结果
                if query_btn or filter_value:
                    if filter_type == "全部":
                        df = get_login_records()
                    elif filter_type == "按用户ID":
                        df = get_login_records("by_user", filter_value if filter_value else None)
                    elif filter_type == "按用户名":
                        df = get_login_records("by_username", filter_value if filter_value else None)
                    elif filter_type == "按日期":
                        df = get_login_records("by_date", filter_value if filter_value else None)
                    st.write(f"### 查询结果（共{len(df)}条）")
                    st.dataframe(df, use_container_width=True)
                else:
                    # 默认显示所有记录
                    df = get_login_records()
                    st.write(f"### 所有登录记录（共{len(df)}条）")
                    st.dataframe(df, use_container_width=True)
            else:
                st.subheader("🔍 我的登录记录")
                df = get_login_records(user_id=st.session_state.user_id)
                st.dataframe(df, use_container_width=True)

                # 数据统计
        elif choice == "数据统计":
            if st.session_state.role == "admin":
                st.subheader("📊 数据统计分析（含可视化）")
                conn = get_db_connection()
                if conn:
                    # 1. 商品购买及好评统计表格
                    st.write("### 商品购买及好评统计")
                    stats_df = get_product_stats()
                    st.dataframe(stats_df, use_container_width=True)
            
                    # 2. 商品可视化图表（修复列名不匹配）
                    st.divider()
                    st.write("### 商品数据可视化")
                    
                    if not stats_df.empty:
                        # 2.1 商品购买人数TOP10（柱状图）
                        top10_buy = stats_df.nlargest(10, "购买人数")
                        fig_buy_top10 = px.bar(
                            top10_buy,
                            x="商品名称",
                            y="购买人数",
                            title="商品购买人数TOP10",
                            color="购买人数",
                            color_continuous_scale=px.colors.sequential.Blues,
                            text="购买人数"
                        )
                        fig_buy_top10.update_layout(xaxis_title="商品名称", yaxis_title="购买人数", xaxis_tickangle=-45)
            
                        # 2.2 商品分类的平均购买人数（饼图）
                        # 修复：将category列重命名为中文“分类”，确保和后续引用一致
                        category_sql = "SELECT product_id AS 商品ID, category AS 分类 FROM products"
                        category_data = pd.read_sql(category_sql, conn)
                        # 合并数据（用“商品ID”作为键）
                        stats_with_category = pd.merge(stats_df, category_data, on="商品ID", how="left")
                        # 过滤“分类”为空的数据
                        stats_with_category = stats_with_category.dropna(subset=["分类"])
                        
                        if not stats_with_category.empty:
                            category_buy = stats_with_category.groupby("分类")["购买人数"].mean().reset_index()
                            fig_category_buy = px.pie(
                                category_buy,
                                values="购买人数",
                                names="分类",
                                title="各商品分类的平均购买人数",
                                hole=0.4,
                                color_discrete_sequence=px.colors.qualitative.Pastel
                            )
                            fig_category_buy.update_traces(textposition="inside", textinfo="percent+label")
                        else:
                            st.warning("暂无商品分类数据，无法生成分类饼图")
            
                        # 2.3 商品好评率分布（直方图）
                        fig_rating = px.histogram(
                            stats_df.dropna(subset=["平均评分"]),
                            x="平均评分",
                            title="商品平均评分分布",
                            nbins=5,
                            color="平均评分",
                            color_discrete_sequence=px.colors.qualitative.Vivid
                        )
                        fig_rating.update_layout(xaxis_title="平均评分", yaxis_title="商品数量")
            
                        # 分栏展示
                        col1, col2 = st.columns(2)
                        with col1:
                            st.plotly_chart(fig_buy_top10, use_container_width=True)
                        with col2:
                            if 'fig_category_buy' in locals():
                                st.plotly_chart(fig_category_buy, use_container_width=True)
                        st.plotly_chart(fig_rating, use_container_width=True)
                    else:
                        st.info("暂无足够数据生成可视化图表")
            
                    conn.close()
            else:
                st.subheader("📈 数据统计分析（基础版）")
                # 商品购买统计
                st.write("### 商品购买及好评统计")
                stats_df = get_product_stats()
                st.dataframe(stats_df, use_container_width=True)

                # 商品购买趋势
                st.write("### 商品购买趋势")
                conn = get_db_connection()
                if conn:
                    product_list = pd.read_sql("SELECT product_id AS 商品ID, product_name FROM products", conn)["product_name"].tolist()
                    conn.close()
                    if product_list:
                        selected_product = st.selectbox("选择商品", product_list)
                        # 修复：通过“商品名称”匹配“商品ID”时，避免空值
                        if not stats_df.empty:
                            product_id = stats_df[stats_df["商品名称"] == selected_product]["商品ID"].iloc[0]
                            trend_df = get_product_trend(product_id)
                            if not trend_df.empty:
                                fig = px.line(trend_df, x="日期", y="日购买量", title=f"{selected_product} 购买趋势")
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("暂无该商品的购买趋势数据")
                        else:
                            st.info("暂无商品统计数据，无法查询趋势")
                    else:
                        st.info("暂无商品数据")
                else:
                    st.info("数据库连接失败，无法加载商品列表")

                # 交易记录
        elif choice == "交易记录":
            if st.session_state.role == "admin":
                st.subheader("📝 交易记录管理")
                
                # 1. 查询订单
                st.write("### 查询订单")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    order_filter = st.selectbox("筛选类型", ["全部", "按订单ID", "按用户ID", "按状态", "按日期"])
                with col2:
                    order_filter_val = st.text_input("筛选值", placeholder="订单ID/用户ID/状态/日期")
                with col3:
                    # 状态选项（中文展示）
                    status_options_cn = ["待付款", "已付款", "已发货", "已完成", "已取消"]
                    new_status = st.selectbox("选择新状态", ["请选择状态"] + status_options_cn)
                with col4:
                    # 新增：订单ID输入框（指定要修改的订单）
                    target_order_id = st.number_input("订单ID", min_value=1, step=1, label_visibility="visible")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    query_order_btn = st.button("查询订单", type="primary")
                with col_btn2:
                    update_status_btn = st.button("修改订单状态", type="secondary")
                
                # 显示订单列表（包含订单ID，方便用户复制）
                if query_order_btn or order_filter_val:
                    if order_filter == "全部":
                        order_df = get_orders()
                    elif order_filter == "按订单ID":
                        order_df = get_orders("by_id", order_filter_val if order_filter_val else None)
                    elif order_filter == "按用户ID":
                        order_df = get_orders("by_user", order_filter_val if order_filter_val else None)
                    elif order_filter == "按状态":
                        # 中文转英文状态
                        status_map_cn2en = {
                            "待付款": "pending", "已付款": "paid", 
                            "已发货": "shipped", "已完成": "completed", "已取消": "cancelled"
                        }
                        val = status_map_cn2en.get(order_filter_val, order_filter_val)
                        order_df = get_orders("by_status", val)
                    elif order_filter == "按日期":
                        order_df = get_orders("by_date", order_filter_val if order_filter_val else None)
                    st.write(f"### 订单列表（共{len(order_df)}条，显示前100条）")
                    st.dataframe(order_df.head(100), use_container_width=True)
                else:
                    # 默认显示前100条
                    order_df = get_orders()
                    st.write(f"### 订单列表（共{len(order_df)}条，显示前100条）")
                    st.dataframe(order_df.head(100), use_container_width=True)
                
                # 修改订单状态（修复：绑定订单ID+状态）
                if update_status_btn:
                    # 校验输入
                    if new_status == "请选择状态":
                        st.warning("请选择要修改的状态！")
                    elif target_order_id < 1:
                        st.warning("请输入有效的订单ID！")
                    else:
                        # 中文状态转英文（匹配数据库）
                        status_map_cn2en = {
                            "待付款": "pending", "已付款": "paid", 
                            "已发货": "shipped", "已完成": "completed", "已取消": "cancelled"
                        }
                        en_status = status_map_cn2en[new_status]
                        
                        # 执行修改
                        success, msg = update_order_status(target_order_id, en_status)
                        if success:
                            st.success(f"订单ID {target_order_id} 的状态已修改为「{new_status}」！")
                            st.rerun()  # 修改后刷新页面
                        else:
                            st.error(f"修改失败：{msg}")
            else:
                st.subheader("📝 我的交易记录")
                # 筛选状态
                status_filter = st.selectbox("筛选状态", ["全部", "待付款", "已付款", "已发货", "已完成", "已取消"])
                status_map = {"全部": None, "待付款": "pending", "已付款": "paid", "已发货": "shipped", "已完成": "completed", "已取消": "cancelled"}
                if status_filter == "全部":
                    order_df = get_orders(user_id=st.session_state.user_id)
                else:
                    order_df = get_orders("by_status", status_map[status_filter], user_id=st.session_state.user_id)
                st.dataframe(order_df, use_container_width=True)




                
        # 用户管理（管理员）
        elif choice == "用户管理" and st.session_state.role == "admin":
            st.subheader("👥 用户管理")
            
            # 选项卡
            tab1, tab2, tab3, tab4 = st.tabs(["查询用户", "新增用户", "修改用户", "删除用户"])
            
            # 1. 查询用户
            with tab1:
                col1, col2, col3 = st.columns(3)
                with col1:
                    user_filter = st.selectbox("筛选类型", ["全部", "按用户ID", "按用户名", "按角色"])
                with col2:
                    user_filter_val = st.text_input("筛选值", placeholder="用户ID/用户名/角色(user/merchant/admin)")
                with col3:
                    query_user_btn = st.button("查询", type="primary")
                
                if query_user_btn or user_filter_val:
                    if user_filter == "全部":
                        user_df = get_users()
                    elif user_filter == "按用户ID":
                        user_df = get_users("by_id", user_filter_val if user_filter_val else None)
                    elif user_filter == "按用户名":
                        user_df = get_users("by_username", user_filter_val if user_filter_val else None)
                    elif user_filter == "按角色":
                        user_df = get_users("by_role", user_filter_val if user_filter_val else None)
                else:
                    user_df = get_users()
                st.write(f"### 用户列表（共{len(user_df)}条）")
                st.dataframe(user_df, use_container_width=True)
            
            # 2. 新增用户
            with tab2:
                with st.form("add_user_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        new_username = st.text_input("用户名", placeholder="请输入唯一用户名")
                        new_password = st.text_input("密码", type="password", placeholder="请输入密码")
                    with col2:
                        new_role = st.selectbox("角色", ["user", "merchant", "admin"])
                        new_phone = st.text_input("手机号", placeholder="选填")
                        new_address = st.text_input("地址", placeholder="选填")
                    submit_add = st.form_submit_button("新增用户", type="primary")
                
                if submit_add:
                    if not new_username or not new_password:
                        st.warning("用户名和密码不能为空！")
                    else:
                        success, msg = add_user(new_username, new_password, new_role, new_phone, new_address)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
            
            # 3. 修改用户（新增用户名、密码输入）
            with tab3:
                with st.form("update_user_form"):
                    # 调整布局，加入“新用户名、新密码”
                    col1, col2 = st.columns(2)
                    with col1:
                        update_user_id = st.number_input("用户ID", min_value=1, step=1)
                        update_username = st.text_input("新用户名", placeholder="不修改则留空（需唯一）")
                        update_password = st.text_input("新密码", type="password", placeholder="不修改则留空")  # 密码输入框（隐藏明文）
                        update_role = st.selectbox("新角色", ["", "user", "merchant", "admin"])
                    with col2:
                        update_phone = st.text_input("新手机号", placeholder="不修改则留空")
                        update_address = st.text_input("新地址", placeholder="不修改则留空")
                    submit_update = st.form_submit_button("修改用户", type="primary")
                
                if submit_update:
                    # 调用修改函数（新增password参数）
                    success, msg = update_user(
                        update_user_id,
                        update_username if update_username else None,
                        update_password if update_password else None,  # 传递新密码
                        update_role if update_role else None,
                        update_phone if update_phone else None,
                        update_address if update_address else None
                    )
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
            
            # 4. 删除用户
            with tab4:
                delete_user_id = st.number_input("用户ID", min_value=1, step=1)
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("删除用户", type="primary"):
                        success, msg = delete_user(delete_user_id)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
                with col2:
                    st.info("删除前请确认该用户无关联数据！")

        # 商家管理（管理员）
        elif choice == "商家管理" and st.session_state.role == "admin":
            st.subheader("🏪 商家管理")
            
            # 选项卡
            tab1, tab2, tab3, tab4 = st.tabs(["查询商家", "新增商家", "修改商家", "删除商家"])
            
            # 1. 查询商家
            with tab1:
                col1, col2, col3 = st.columns(3)
                with col1:
                    merchant_filter = st.selectbox("筛选类型", ["全部", "按商家ID", "按商家名称", "按最低评分"])
                with col2:
                    merchant_filter_val = st.text_input("筛选值", placeholder="商家ID/名称/评分")
                with col3:
                    query_merchant_btn = st.button("查询", type="primary")
                
                if query_merchant_btn or merchant_filter_val:
                    if merchant_filter == "全部":
                        merchant_df = get_merchants()
                    elif merchant_filter == "按商家ID":
                        merchant_df = get_merchants("by_id", merchant_filter_val if merchant_filter_val else None)
                    elif merchant_filter == "按商家名称":
                        merchant_df = get_merchants("by_name", merchant_filter_val if merchant_filter_val else None)
                    elif merchant_filter == "按最低评分":
                        merchant_df = get_merchants("by_rating", merchant_filter_val if merchant_filter_val else None)
                else:
                    merchant_df = get_merchants()
                st.write(f"### 商家列表（共{len(merchant_df)}条）")
                st.dataframe(merchant_df, use_container_width=True)
            
            # 2. 新增商家
            with tab2:
                with st.form("add_merchant_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        new_merchant_user_id = st.number_input("关联用户ID", min_value=1, step=1)
                        new_merchant_name = st.text_input("商家名称", placeholder="请输入商家名称")
                    with col2:
                        new_business_license = st.text_input("营业执照号", placeholder="请输入营业执照号")
                        new_contact_phone = st.text_input("联系电话", placeholder="请输入联系电话")
                        new_rating = st.number_input("初始评分", min_value=0.0, max_value=5.0, step=0.1)
                    submit_add = st.form_submit_button("新增商家", type="primary")
                
                if submit_add:
                    if not new_merchant_name or not new_business_license:
                        st.warning("商家名称和营业执照号不能为空！")
                    else:
                        success, msg = add_merchant(
                            new_merchant_user_id, new_merchant_name,
                            new_business_license, new_contact_phone, new_rating
                        )
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
            
            # 3. 修改商家
            with tab3:
                with st.form("update_merchant_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        update_merchant_id = st.number_input("商家ID", min_value=1, step=1)
                        update_merchant_name = st.text_input("新商家名称", placeholder="不修改则留空")
                        update_business_license = st.text_input("新营业执照号", placeholder="不修改则留空")
                    with col2:
                        update_contact_phone = st.text_input("新联系电话", placeholder="不修改则留空")
                        update_rating = st.number_input("新评分", min_value=0.0, max_value=5.0, step=0.1, value=0.0)
                    submit_update = st.form_submit_button("修改商家", type="primary")
                
                if submit_update:
                    success, msg = update_merchant(
                        update_merchant_id,
                        update_merchant_name if update_merchant_name else None,
                        update_business_license if update_business_license else None,
                        update_contact_phone if update_contact_phone else None,
                        update_rating if update_rating > 0 else None
                    )
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
            
            # 4. 删除商家
            with tab4:
                delete_merchant_id = st.number_input("商家ID", min_value=1, step=1)
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("删除商家", type="primary"):
                        success, msg = delete_merchant(delete_merchant_id)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
                with col2:
                    st.info("删除前请确认该商家无关联商品/订单！")

        # 商品管理（管理员）
        elif choice == "商品管理" and st.session_state.role == "admin":
            st.subheader("📦 商品管理")
            
            # 选项卡
            tab1, tab2, tab3, tab4 = st.tabs(["查询商品", "新增商品", "修改商品", "删除商品"])
            
            # 1. 查询商品
            with tab1:
                col1, col2, col3 = st.columns(3)
                with col1:
                    product_filter = st.selectbox("筛选类型", ["全部", "按商品ID", "按商品名称", "按分类", "按商家ID"])
                with col2:
                    product_filter_val = st.text_input("筛选值", placeholder="商品ID/名称/分类/商家ID")
                with col3:
                    query_product_btn = st.button("查询", type="primary")
                
                if query_product_btn or product_filter_val:
                    if product_filter == "全部":
                        product_df = get_products()
                    elif product_filter == "按商品ID":
                        product_df = get_products("by_id", product_filter_val if product_filter_val else None)
                    elif product_filter == "按商品名称":
                        product_df = get_products("by_name", product_filter_val if product_filter_val else None)
                    elif product_filter == "按分类":
                        product_df = get_products("by_category", product_filter_val if product_filter_val else None)
                    elif product_filter == "按商家ID":
                        product_df = get_products("by_merchant", product_filter_val if product_filter_val else None)
                else:
                    product_df = get_products()
                st.write(f"### 商品列表（共{len(product_df)}条）")
                st.dataframe(product_df, use_container_width=True)
            
            # 2. 新增商品
            with tab2:
                with st.form("add_product_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        new_product_merchant_id = st.number_input("商家ID", min_value=1, step=1)
                        new_product_name = st.text_input("商品名称", placeholder="请输入商品名称")
                        new_product_price = st.number_input("商品价格", min_value=0.01, step=0.01)
                    with col2:
                        new_product_stock = st.number_input("商品库存", min_value=0, step=1)
                        new_product_category = st.text_input("商品分类", placeholder="如：电子产品、服装")
                    submit_add = st.form_submit_button("新增商品", type="primary")
                
                if submit_add:
                    if not new_product_name or not new_product_category:
                        st.warning("商品名称和分类不能为空！")
                    else:
                        success, msg = add_product(
                            new_product_merchant_id, new_product_name,
                            new_product_price, new_product_stock, new_product_category
                        )
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
            
                        # 3. 修改商品
            with tab3:
                with st.form("update_product_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        update_product_id = st.number_input("商品ID", min_value=1, step=1)
                        update_product_name = st.text_input("新商品名称", placeholder="不修改则留空")
                        update_product_price = st.number_input("新价格", min_value=0.01, step=0.01, value=0.01, format="%.2f")
                    with col2:
                        update_product_stock = st.number_input("新库存", min_value=0, step=1, value=0)
                        update_product_category = st.text_input("新分类", placeholder="不修改则留空")
                    submit_update = st.form_submit_button("修改商品", type="primary")
                
                if submit_update:
                    # 处理空值（留空则不修改对应字段）
                    price_val = update_product_price if update_product_price > 0.01 else None
                    stock_val = update_product_stock if update_product_stock >= 0 else None
                    
                    success, msg = update_product(
                        update_product_id,
                        update_product_name if update_product_name else None,
                        price_val,
                        stock_val,
                        update_product_category if update_product_category else None
                    )
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
            
            # 4. 删除商品
            with tab4:
                delete_product_id = st.number_input("商品ID", min_value=1, step=1)
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("删除商品", type="primary"):
                        success, msg = delete_product(delete_product_id)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
                with col2:
                    st.info("删除前请确认该商品无关联订单！删除后无法恢复")

        # 管理员-客服管理
        elif choice == "客服管理" and st.session_state.role == "admin":
            st.subheader("📞 客服记录管理")
            
            # 选项卡
            tab1, tab2 = st.tabs(["查询客服记录", "回复客服咨询"])
            
            # 1. 查询客服记录
            with tab1:
                col1, col2, col3 = st.columns(3)
                with col1:
                    cs_filter = st.selectbox("筛选类型", ["全部", "按记录ID", "按用户ID", "按商家ID"])
                with col2:
                    cs_filter_val = st.text_input("筛选值", placeholder="记录ID/用户ID/商家ID")
                with col3:
                    cs_reply_filter = st.selectbox("回复状态", ["全部", "已回复", "未回复"])
                
                query_cs_btn = st.button("查询记录", type="primary")
                
                # 处理查询逻辑
                if query_cs_btn or cs_filter_val:
                    is_replied = None
                    if cs_reply_filter == "已回复":
                        is_replied = True
                    elif cs_reply_filter == "未回复":
                        is_replied = False
                    
                    if cs_filter == "全部":
                        cs_df = get_cs_records(is_replied=is_replied)
                    elif cs_filter == "按记录ID":
                        cs_df = get_cs_records("by_id", cs_filter_val if cs_filter_val else None, is_replied=is_replied)
                    elif cs_filter == "按用户ID":
                        cs_df = get_cs_records("by_user", cs_filter_val if cs_filter_val else None, is_replied=is_replied)
                    elif cs_filter == "按商家ID":
                        cs_df = get_cs_records("by_merchant", cs_filter_val if cs_filter_val else None, is_replied=is_replied)
                else:
                    cs_df = get_cs_records()
                
                st.write(f"### 客服记录列表（共{len(cs_df)}条）")
                st.dataframe(cs_df, use_container_width=True)
            
            # 2. 回复客服咨询
            with tab2:
                with st.form("reply_cs_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        reply_cs_id = st.number_input("客服记录ID", min_value=1, step=1)
                    with col2:
                        reply_content = st.text_area("回复内容", placeholder="请输入回复内容", height=100)
                    
                    submit_reply = st.form_submit_button("提交回复", type="primary")
                
                if submit_reply:
                    if not reply_content.strip():
                        st.warning("回复内容不能为空！")
                    else:
                        success, msg = reply_cs_record(reply_cs_id, reply_content)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)

        # 商家-我的商品
        elif choice == "我的商品" and st.session_state.role == "merchant":
            st.subheader("🛍️ 我的商品管理")
            
            # 获取当前商家ID
            conn = get_db_connection()
            if conn:
                merchant_id = pd.read_sql(
                    "SELECT merchant_id FROM merchants WHERE user_id=%s", 
                    conn, params=(st.session_state.user_id,)
                ).iloc[0,0]
                conn.close()
                
                # 选项卡
                tab1, tab2, tab3 = st.tabs(["我的商品列表", "新增商品", "修改/删除商品"])
                
                # 1. 我的商品列表
                with tab1:
                    # 简单筛选
                    col1, col2 = st.columns(2)
                    with col1:
                        prod_name_filter = st.text_input("商品名称筛选", placeholder="输入关键词")
                    with col2:
                        prod_category_filter = st.text_input("分类筛选", placeholder="如：电子产品")
                    
                    query_btn = st.button("筛选", type="primary")
                    
                    # 查询逻辑
                    if query_btn or prod_name_filter or prod_category_filter:
                        df = get_products()
                        if prod_name_filter:
                            df = df[df["product_name"].str.contains(prod_name_filter, na=False)]
                        if prod_category_filter:
                            df = df[df["category"] == prod_category_filter]
                        df = df[df["merchant_id"] == merchant_id]
                    else:
                        df = get_products(merchant_id=merchant_id)
                    
                    st.write(f"### 我的商品（共{len(df)}条）")
                    st.dataframe(df, use_container_width=True)
                
                # 2. 新增商品
                with tab2:
                    with st.form("merchant_add_product_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            new_prod_name = st.text_input("商品名称", placeholder="请输入商品名称")
                            new_prod_price = st.number_input("商品价格", min_value=0.01, step=0.01, format="%.2f")
                        with col2:
                            new_prod_stock = st.number_input("商品库存", min_value=0, step=1)
                            new_prod_category = st.text_input("商品分类", placeholder="如：电子产品、服装")
                        
                        submit_add = st.form_submit_button("新增商品", type="primary")
                    
                    if submit_add:
                        if not new_prod_name or not new_prod_category:
                            st.warning("商品名称和分类不能为空！")
                        else:
                            success, msg = add_product(merchant_id, new_prod_name, new_prod_price, new_prod_stock, new_prod_category)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                
                # 3. 修改/删除商品
                with tab3:
                    col1, col2 = st.columns(2)
                    
                    # 修改商品
                    with col1:
                        st.subheader("修改商品")
                        with st.form("merchant_update_product_form"):
                            update_prod_id = st.number_input("商品ID", min_value=1, step=1)
                            update_prod_name = st.text_input("新商品名称", placeholder="不修改则留空")
                            update_prod_price = st.number_input("新价格", min_value=0.01, step=0.01, value=0.01, format="%.2f")
                            update_prod_stock = st.number_input("新库存", min_value=0, step=1, value=0)
                            update_prod_category = st.text_input("新分类", placeholder="不修改则留空")
                            
                            submit_update = st.form_submit_button("修改商品")
                        
                        if submit_update:
                            price_val = update_prod_price if update_prod_price > 0.01 else None
                            stock_val = update_prod_stock if update_prod_stock >= 0 else None
                            
                            success, msg = update_product(
                                update_prod_id,
                                update_prod_name if update_prod_name else None,
                                price_val,
                                stock_val,
                                update_prod_category if update_prod_category else None
                            )
                            if success:
                                st.success(msg)
                            else:
                                st.error(msg)
                    
                    # 删除商品
                    with col2:
                        st.subheader("删除商品")
                        delete_prod_id = st.number_input("商品ID", min_value=1, step=1)
                        if st.button("删除商品", type="primary"):
                            success, msg = delete_product(delete_prod_id)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

        # 商家-我的订单
        elif choice == "我的订单" and st.session_state.role == "merchant":
            st.subheader("📦 我的订单管理")
            
            # 获取当前商家ID
            conn = get_db_connection()
            if conn:
                merchant_id = pd.read_sql(
                    "SELECT merchant_id FROM merchants WHERE user_id=%s", 
                    conn, params=(st.session_state.user_id,)
                ).iloc[0,0]
                
                # 获取该商家的商品ID列表
                prod_ids = pd.read_sql(
                    "SELECT product_id FROM products WHERE merchant_id=%s",
                    conn, params=(merchant_id,)
                )["product_id"].tolist()
                conn.close()
                
                if prod_ids:
                    # 筛选条件
                    col1, col2 = st.columns(2)
                    with col1:
                        order_status_filter = st.selectbox("订单状态", ["全部", "待付款", "已付款", "已发货", "已完成", "已取消"])
                    with col2:
                        date_filter = st.date_input("日期筛选", value=None)
                    
                    query_btn = st.button("筛选订单", type="primary")
                    
                    # 构建查询条件
                    status_map = {"全部": None, "待付款": "pending", "已付款": "paid", "已发货": "shipped", "已完成": "completed", "已取消": "cancelled"}
                    status_val = status_map[order_status_filter]
                    
                    # 查询订单
                    all_orders = get_orders()
                    # 筛选当前商家的订单（通过商品ID关联）
                    merchant_orders = all_orders[all_orders["product_id"].isin(prod_ids)]
                    
                    # 应用筛选
                    if query_btn or order_status_filter != "全部" or date_filter:
                        if status_val:
                            merchant_orders = merchant_orders[merchant_orders["status"] == status_val]
                        if date_filter:
                            merchant_orders["order_time"] = pd.to_datetime(merchant_orders["order_time"])
                            merchant_orders = merchant_orders[merchant_orders["order_time"].dt.date == date_filter]
                    
                    st.write(f"### 我的订单（共{len(merchant_orders)}条）")
                    st.dataframe(merchant_orders, use_container_width=True)
                    
                    # 修改订单状态
                    st.divider()
                    st.subheader("修改订单状态")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        update_order_id = st.number_input("订单ID", min_value=1, step=1)
                    with col2:
                        new_order_status = st.selectbox("新状态", ["待付款", "已付款", "已发货", "已完成", "已取消"])
                    with col3:
                        if st.button("确认修改", type="primary"):
                            status_en = status_map[new_order_status]
                            success, msg = update_order_status(update_order_id, status_en)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                else:
                    st.info("暂无商品，暂无订单数据")

        # 商家-评价管理
        elif choice == "评价管理" and st.session_state.role == "merchant":
            st.subheader("⭐ 商品评价管理")
            
            # 获取当前商家ID和商品ID
            conn = get_db_connection()
            if conn:
                merchant_id = pd.read_sql(
                    "SELECT merchant_id FROM merchants WHERE user_id=%s", 
                    conn, params=(st.session_state.user_id,)
                ).iloc[0,0]
                
                # 关联评价-订单-商品-商家
                query = """
                SELECT r.review_id, o.order_id, p.product_name, u.username, 
                       r.rating, r.comment, r.review_time
                FROM reviews r
                LEFT JOIN orders o ON r.order_id = o.order_id
                LEFT JOIN products p ON o.product_id = p.product_id
                LEFT JOIN users u ON o.user_id = u.user_id
                WHERE p.merchant_id = %s
                ORDER BY r.review_time DESC
                """
                review_df = pd.read_sql(query, conn, params=(merchant_id,))
                conn.close()
                
                if not review_df.empty:
                    # 筛选
                    col1, col2 = st.columns(2)
                    with col1:
                        rating_filter = st.selectbox("评分筛选", ["全部", 1, 2, 3, 4, 5])
                    with col2:
                        prod_name_filter = st.text_input("商品名称筛选", placeholder="输入关键词")
                    
                    query_btn = st.button("筛选评价", type="primary")
                    
                    # 应用筛选
                    if query_btn or rating_filter != "全部" or prod_name_filter:
                        if rating_filter != "全部":
                            review_df = review_df[review_df["rating"] == rating_filter]
                        if prod_name_filter:
                            review_df = review_df[review_df["product_name"].str.contains(prod_name_filter, na=False)]
                    
                    st.write(f"### 评价列表（共{len(review_df)}条）")
                    st.dataframe(review_df, use_container_width=True)
                    
                    # 统计
                    st.divider()
                    st.subheader("评价统计")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        avg_rating = review_df["rating"].mean()
                        st.metric("平均评分", f"{avg_rating:.1f}")
                    with col2:
                        positive_rate = len(review_df[review_df["rating"] >= 4]) / len(review_df) * 100
                        st.metric("好评率(≥4分)", f"{positive_rate:.1f}%")
                    with col3:
                        total_reviews = len(review_df)
                        st.metric("总评价数", total_reviews)
                    
                    # 可视化
                    fig_rating = px.histogram(
                        review_df,
                        x="rating",
                        title="评分分布",
                        nbins=5,
                        color="rating",
                        color_discrete_sequence=px.colors.sequential.Rainbow
                    )
                    st.plotly_chart(fig_rating, use_container_width=True)
                else:
                    st.info("暂无商品评价数据")

        # 普通用户-我的订单
        elif choice == "我的订单" and st.session_state.role == "user":
            st.subheader("📝 我的订单")
            
            # 筛选条件
            col1, col2 = st.columns(2)
            with col1:
                order_status_filter = st.selectbox("订单状态", ["全部", "待付款", "已付款", "已发货", "已完成", "已取消"])
            with col2:
                date_filter = st.date_input("下单日期", value=None)
            
            query_btn = st.button("筛选订单", type="primary")
            
            # 查询我的订单
            my_orders = get_orders(user_id=st.session_state.user_id)
            
            # 应用筛选
            if query_btn or order_status_filter != "全部" or date_filter:
                status_map = {"全部": None, "待付款": "pending", "已付款": "paid", "已发货": "shipped", "已完成": "completed", "已取消": "cancelled"}
                if order_status_filter != "全部":
                    my_orders = my_orders[my_orders["status"] == status_map[order_status_filter]]
                if date_filter:
                    my_orders["order_time"] = pd.to_datetime(my_orders["order_time"])
                    my_orders = my_orders[my_orders["order_time"].dt.date == date_filter]
            
            st.dataframe(my_orders, use_container_width=True)
            
            # 查看物流
            st.divider()
            st.subheader("查看物流")
            order_id = st.number_input("订单ID", min_value=1, step=1)
            if st.button("查询物流"):
                conn = get_db_connection()
                if conn:
                    logistics_df = pd.read_sql(
                        "SELECT * FROM logistics WHERE order_id=%s",
                        conn, params=(order_id,)
                    )
                    conn.close()
                    if not logistics_df.empty:
                        st.write("### 物流信息")
                        st.dataframe(logistics_df, use_container_width=True)
                    else:
                        st.info("暂无该订单的物流信息")

        # 普通用户-我的评价
        elif choice == "我的评价" and st.session_state.role == "user":
            st.subheader("⭐ 我的评价")
            
            # 查询我的评价
            conn = get_db_connection()
            if conn:
                query = """
                SELECT r.review_id, o.order_id, p.product_name, r.rating, 
                       r.comment, r.review_time
                FROM reviews r
                LEFT JOIN orders o ON r.order_id = o.order_id
                LEFT JOIN products p ON o.product_id = p.product_id
                WHERE o.user_id = %s
                ORDER BY r.review_time DESC
                """
                my_reviews = pd.read_sql(query, conn, params=(st.session_state.user_id,))
                conn.close()
                
                if not my_reviews.empty:
                    st.dataframe(my_reviews, use_container_width=True)
                    
                    # 新增评价
                    st.divider()
                    st.subheader("新增评价")
                    with st.form("add_review_form"):
                        order_id = st.number_input("订单ID", min_value=1, step=1)
                        rating = st.slider("评分", 1, 5, 3)
                        comment = st.text_area("评价内容", placeholder="请输入评价内容", height=100)
                        submit_review = st.form_submit_button("提交评价", type="primary")
                    
                    if submit_review:
                        if not comment.strip():
                            st.warning("评价内容不能为空！")
                        else:
                            conn = get_db_connection()
                            if conn:
                                cursor = conn.cursor()
                                try:
                                    # 检查订单是否属于当前用户且未评价
                                    cursor.execute(
                                        "SELECT * FROM orders WHERE order_id=%s AND user_id=%s",
                                        (order_id, st.session_state.user_id)
                                    )
                                    order = cursor.fetchone()
                                    
                                    cursor.execute(
                                        "SELECT * FROM reviews WHERE order_id=%s",
                                        (order_id,)
                                    )
                                    existing_review = cursor.fetchone()
                                    
                                    if not order:
                                        st.error("该订单不存在或不属于您！")
                                    elif existing_review:
                                        st.error("该订单已评价，无法重复评价！")
                                    else:
                                        cursor.execute(
                                            "INSERT INTO reviews (order_id, rating, comment) VALUES (%s, %s, %s)",
                                            (order_id, rating, comment)
                                        )
                                        conn.commit()
                                        st.success("评价提交成功！")
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"提交失败：{str(e)}")
                                finally:
                                    cursor.close()
                                    conn.close()
                else:
                    st.info("暂无评价数据，可对已完成订单进行评价")

        # 普通用户-客服中心
        elif choice == "客服中心" and st.session_state.role == "user":
            st.subheader("📞 客服中心")
            
            # 选项卡
            tab1, tab2 = st.tabs(["我的咨询", "提交新咨询"])
            
            # 1. 我的咨询
            with tab1:
                conn = get_db_connection()
                if conn:
                    my_cs = pd.read_sql(
                        "SELECT * FROM customer_service WHERE user_id=%s ORDER BY create_time DESC",
                        conn, params=(st.session_state.user_id,)
                    )
                    conn.close()
                    st.dataframe(my_cs, use_container_width=True)
            
            # 2. 提交新咨询
            with tab2:
                with st.form("add_cs_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        merchant_id = st.number_input("商家ID（可选）", min_value=1, step=1, value=0)
                    with col2:
                        pass  # 预留字段
                    content = st.text_area("咨询内容", placeholder="请详细描述您的问题", height=150)
                    submit_cs = st.form_submit_button("提交咨询", type="primary")
                
                if submit_cs:
                    if not content.strip():
                        st.warning("咨询内容不能为空！")
                    else:
                        conn = get_db_connection()
                        if conn:
                            cursor = conn.cursor()
                            try:
                                # 处理可选的商家ID
                                merchant_id_val = merchant_id if merchant_id > 0 else None
                                cursor.execute(
                                    """
                                    INSERT INTO customer_service (user_id, merchant_id, content) 
                                    VALUES (%s, %s, %s)
                                    """,
                                    (st.session_state.user_id, merchant_id_val, content)
                                )
                                conn.commit()
                                st.success("咨询提交成功！客服将尽快回复")
                                st.rerun()
                            except Exception as e:
                                st.error(f"提交失败：{str(e)}")
                            finally:
                                cursor.close()
                                conn.close()

        # 普通用户-商家推荐
        elif choice == "商家推荐" and st.session_state.role == "user":
            st.subheader("🏆 优质商家推荐")
            
            # 获取TOP5商家
            top_merchants = get_top_merchants()
            if not top_merchants.empty:
                st.dataframe(top_merchants, use_container_width=True)
                
                # 可视化商家评分
                fig = px.bar(
                    top_merchants,
                    x="merchant_name",
                    y="rating",
                    title="Top5优质商家评分",
                    color="rating",
                    color_continuous_scale=px.colors.sequential.Greens,
                    text="rating"
                )
                fig.update_layout(xaxis_title="商家名称", yaxis_title="评分", xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
                
                # 查看商家商品
                st.divider()
                st.subheader("查看商家商品")
                selected_merchant = st.selectbox("选择商家", top_merchants["merchant_name"].tolist())
                merchant_id = top_merchants[top_merchants["merchant_name"] == selected_merchant]["merchant_id"].iloc[0]
                
                merchant_products = get_products("by_merchant", merchant_id)
                st.write(f"### {selected_merchant} 的商品（共{len(merchant_products)}条）")
                st.dataframe(merchant_products, use_container_width=True)
            else:
                st.info("暂无商家推荐数据")

# 启动应用
if __name__ == "__main__":
    main()