from flask import Flask, request, jsonify
import mysql.connector
from flask_cors import CORS
import os
from pyzbar.pyzbar import decode
import json
import cv2


app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "products_qr_codes"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Function to get a new database connection
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="ims_db"
    )

@app.route('/api/products', methods=['GET'])
def get_products():
    db = get_db_connection()  # New connection for each request
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT pid, description, pname, base_price, quantity FROM ims_product")
    products = cursor.fetchall()

    cursor.close()
    db.close()  # Close the connection after use

    return jsonify(products)

@app.route('/api/add_order', methods=['POST'])
def add_order():
    try:
        data = request.get_json()
        cart = data.get("cart", [])

        if not cart:
            return jsonify({"status": "error", "message": "Cart is empty."}), 400

        db = get_db_connection()
        cursor = db.cursor()
        order_ids = []

        for item in cart:
            product_id = item.get("id")
            quantity = item.get("quantity")

            # Get current stock
            cursor.execute("SELECT quantity FROM ims_product WHERE pid = %s", (product_id,))
            result = cursor.fetchone()

            if not result:
                cursor.close()
                db.close()
                return jsonify({"status": "error", "message": f"Product ID {product_id} not found."}), 404

            current_stock = result[0]

            # Check if enough stock is available
            if quantity > current_stock:
                cursor.close()
                db.close()
                return jsonify({"status": "error", "message": f"Not enough stock for product ID {product_id}."}), 400

            # Update stock in database
            # new_stock = current_stock - quantity
            # cursor.execute("UPDATE ims_product SET quantity = %s WHERE pid = %s", (new_stock, product_id))

            cursor.execute(
                "INSERT INTO ims_order (product_id, customer_id) VALUES (%s, %s)",
                (product_id, 1)
            )

            order_id = cursor.lastrowid
            order_ids.append(order_id)

        db.commit()
        cursor.close()
        db.close()

        return jsonify({"status": "success", "message": "Stock updated successfully.", "order_ids": order_ids}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    db = get_db_connection()  # Create a new connection
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
SELECT
    p.pid,
    p.pname AS product_name,
    (SELECT MAX(quantity) FROM ims_product WHERE pid = p.pid) AS starting_inventory,
    COALESCE(SUM(purchase.quantity), 0) AS inventory_received,
    COALESCE(SUM(o.total_shipped), 0) AS inventory_shipped,
    (p.quantity + COALESCE(SUM(purchase.quantity), 0) - COALESCE(SUM(o.total_shipped), 0)) AS inventory_on_hand
FROM ims_product p
LEFT JOIN ims_purchase purchase ON p.pid = purchase.product_id
LEFT JOIN ims_order o ON p.pid = o.product_id
GROUP BY p.pid, p.pname, p.quantity;

    """)

    inventory = cursor.fetchall()
    cursor.close()
    db.close()  # Close the connection

    return jsonify(inventory)

@app.route('/api/add_product', methods=['POST'])
def upload_qr():
    if "qr_code" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    qr_file = request.files["qr_code"]
    file_path = os.path.join(UPLOAD_FOLDER, qr_file.filename)
    qr_file.save(file_path)

    # Process QR Code
    image = cv2.imread(file_path)
    decoded_objects = decode(image)

    if not decoded_objects:
        return jsonify({"status": "error", "message": "QR code not detected"}), 400

    qr_data = decoded_objects[0].data.decode("utf-8")  # Extract QR text
    product_data = json.loads(qr_data)  # Convert JSON string to Python dictionary

    # Save to Database
    db = get_db_connection()
    cursor = db.cursor()

    # Insert into ims_product table
    cursor.execute("""
    INSERT INTO ims_product
    (categoryid, brandid, pname, model, description, quantity, unit, base_price, tax, minimum_order, supplier, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        product_data["category_id"],
        product_data["brand_id"],
        product_data["name"],
        product_data["model"],
        product_data["description"],
        product_data["quantity"],  # Quantity input when adding product
        product_data["unit"],
        product_data["base_price"],
        product_data["tax"],
        product_data["min_order"],
        product_data["supplier"],
        product_data["status"]
    ))

    product_id = cursor.lastrowid  # Get the inserted product ID
    purchase_quantity = product_data["quantity"]  # Set purchase quantity

    cursor.execute("SELECT COUNT(*) FROM ims_purchase WHERE product_id = %s", (product_id,))
    exists = cursor.fetchone()[0]

    if exists == 0:  # Only insert if it doesn’t already exist
        cursor.execute(
        "INSERT INTO ims_purchase (supplier_id, product_id, quantity, purchase_date) VALUES (%s, %s, %s, NOW())",
        (product_data["supplier"], product_id, purchase_quantity)
        )

    db.commit()
    cursor.close()
    db.close()

    return jsonify({"status": "success", "product_id": product_id, "purchase_quantity": purchase_quantity, "product": product_data}), 200


@app.route('/api/update_stock', methods=['POST'])
def update_stock():
    try:
        data = request.get_json()
        products = data.get("products", [])

        if not products:
            return jsonify({"status": "error", "message": "No products provided"}), 400

        db = get_db_connection()
        cursor = db.cursor()

        for item in products:
            product_id = item.get("product_id")
            quantity = int(item.get("quantity", 0))

            if not product_id or quantity <= 0:
                continue  # Skip invalid entries

            # Check current stock
            cursor.execute("SELECT quantity FROM ims_product WHERE pid = %s", (product_id,))
            result = cursor.fetchone()

            if not result:
                continue  # Skip if product not found

            # Update stock
            new_stock = result[0] - quantity
            cursor.execute("UPDATE ims_product SET quantity = %s WHERE pid = %s", (new_stock, product_id))

            cursor.execute(
                """
                UPDATE ims_order
                SET total_shipped = total_shipped + %s, customer_id = %s
                WHERE product_id = %s
                """,
                (quantity, 1, product_id)
            )

        db.commit()
        cursor.close()
        db.close()

        return jsonify({"status": "success", "message": "Stock updated successfully"}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    print("Starting Flask API...")  # Debugging statement
    app.run(debug=True, host='0.0.0.0', port=5000)
