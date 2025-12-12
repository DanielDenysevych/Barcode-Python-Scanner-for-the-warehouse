from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

DATABASE = 'equipment.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with equipment table"""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS equipment (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            location TEXT,
            last_updated TEXT
        )
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/equipment', methods=['GET'])
def get_equipment():
    """Get all equipment"""
    conn = get_db()
    equipment = conn.execute('SELECT * FROM equipment ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(row) for row in equipment])

@app.route('/api/equipment', methods=['POST'])
def add_equipment():
    """Add new equipment"""
    data = request.json
    name = data.get('name')
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    
    # Generate unique ID
    equipment_id = 'EQ' + str(int(datetime.now().timestamp() * 1000))
    
    conn = get_db()
    conn.execute(
        'INSERT INTO equipment (id, name, status, location, last_updated) VALUES (?, ?, ?, ?, ?)',
        (equipment_id, name, 'IN', 'Warehouse', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()
    
    return jsonify({'id': equipment_id, 'name': name, 'message': 'Equipment added successfully'})

@app.route('/api/equipment/<equipment_id>', methods=['DELETE'])
def delete_equipment(equipment_id):
    """Delete equipment"""
    conn = get_db()
    conn.execute('DELETE FROM equipment WHERE id = ?', (equipment_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Equipment deleted successfully'})

@app.route('/api/scan', methods=['POST'])
def scan_equipment():
    """Process equipment scan (check in/out)"""
    data = request.json
    code = data.get('code')
    location = data.get('location', '')
    
    if not code:
        return jsonify({'error': 'Code is required'}), 400
    
    conn = get_db()
    equipment = conn.execute('SELECT * FROM equipment WHERE id = ?', (code,)).fetchone()
    
    if not equipment:
        conn.close()
        return jsonify({'error': 'Equipment not found'}), 404
    
    # Toggle status
    if equipment['status'] == 'IN':
        new_status = 'OUT'
        new_location = location if location else 'Unknown'
        message = f"{equipment['name']} checked OUT to: {new_location}"
    else:
        new_status = 'IN'
        new_location = 'Warehouse'
        message = f"{equipment['name']} checked IN to warehouse"
    
    conn.execute(
        'UPDATE equipment SET status = ?, location = ?, last_updated = ? WHERE id = ?',
        (new_status, new_location, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), code)
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        'message': message,
        'equipment': {
            'id': equipment['id'],
            'name': equipment['name'],
            'status': new_status,
            'location': new_location
        }
    })

@app.route('/api/export', methods=['GET'])
def export_data():
    """Export all equipment data"""
    conn = get_db()
    equipment = conn.execute('SELECT * FROM equipment ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(row) for row in equipment])

@app.route('/api/import', methods=['POST'])
def import_data():
    """Import equipment data"""
    data = request.json
    equipment_list = data.get('equipment', [])
    
    if not equipment_list:
        return jsonify({'error': 'No equipment data provided'}), 400
    
    conn = get_db()
    for item in equipment_list:
        # Check if equipment already exists
        existing = conn.execute('SELECT id FROM equipment WHERE id = ?', (item['id'],)).fetchone()
        if existing:
            # Update existing
            conn.execute(
                'UPDATE equipment SET name = ?, status = ?, location = ?, last_updated = ? WHERE id = ?',
                (item['name'], item['status'], item['location'], item['last_updated'], item['id'])
            )
        else:
            # Insert new
            conn.execute(
                'INSERT INTO equipment (id, name, status, location, last_updated) VALUES (?, ?, ?, ?, ?)',
                (item['id'], item['name'], item['status'], item['location'], item['last_updated'])
            )
    
    conn.commit()
    conn.close()
    
    return jsonify({'message': f'Imported {len(equipment_list)} items successfully'})

if __name__ == '__main__':
    init_db()
    print("\n" + "="*50)
    print("Equipment Tracker Server Starting...")
    print("="*50)
    print("\nOpen your browser and go to:")
    print("http://localhost:5000")
    print("\nPress CTRL+C to stop the server")
    print("="*50 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)