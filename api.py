from flask import Flask, request, jsonify
import mysql.connector
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Database connection
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="ims_db"
)

@app.route('/api/products', methods=['GET'])
def get_products():
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT pid, description, pname, base_price, quantity FROM ims_product")
    products = cursor.fetchall()
    cursor.close()
    
    return jsonify(products)


@app.route('/api/update_stock', methods=['POST'])
def update_stock():
    try:
        data = request.get_json()
        cart = data.get("cart", [])

        if not cart:
            return jsonify({"status": "error", "message": "Cart is empty."}), 400

        cursor = db.cursor()

        for item in cart:
            product_id = item.get("id")
            quantity = item.get("quantity")

            # Get current stock
            cursor.execute("SELECT quantity FROM ims_product WHERE pid = %s", (product_id,))
            result = cursor.fetchone()

            if not result:
                return jsonify({"status": "error", "message": f"Product ID {product_id} not found."}), 404

            current_stock = result[0]

            # Check if enough stock is available
            if quantity > current_stock:
                return jsonify({"status": "error", "message": f"Not enough stock for product ID {product_id}."}), 400

            # Update stock in database
            new_stock = current_stock - quantity
            cursor.execute("UPDATE ims_product SET quantity = %s WHERE pid = %s", (new_stock, product_id))

        db.commit()
        cursor.close()

        return jsonify({"status": "success", "message": "Stock updated successfully."}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
