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
    """Initialize the database with equipment and events tables"""
    conn = get_db()
    
    # Equipment table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS equipment (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            location TEXT,
            last_updated TEXT
        )
    ''')
    
    # Events table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            date TEXT NOT NULL,
            location TEXT,
            status TEXT NOT NULL,
            notes TEXT,
            created_at TEXT
        )
    ''')
    
    # Event equipment checklist table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS event_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            equipment_id TEXT NOT NULL,
            checked_out INTEGER DEFAULT 0,
            checked_in INTEGER DEFAULT 0,
            notes TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(id)
        )
    ''')
    
    # Event templates table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS event_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT
        )
    ''')
    
    # Template equipment items
    conn.execute('''
        CREATE TABLE IF NOT EXISTS template_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id TEXT NOT NULL,
            equipment_name TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            FOREIGN KEY (template_id) REFERENCES event_templates(id)
        )
    ''')
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

# ==================== EQUIPMENT ROUTES ====================

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
    event_id = data.get('event_id', '')
    
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
        
        # If event_id provided, mark as checked out in event checklist
        if event_id:
            conn.execute(
                'UPDATE event_equipment SET checked_out = 1 WHERE event_id = ? AND equipment_id = ?',
                (event_id, code)
            )
    else:
        new_status = 'IN'
        new_location = 'Warehouse'
        message = f"{equipment['name']} checked IN to warehouse"
        
        # If event_id provided, mark as checked in
        if event_id:
            conn.execute(
                'UPDATE event_equipment SET checked_in = 1 WHERE event_id = ? AND equipment_id = ?',
                (event_id, code)
            )
    
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

# ==================== EVENTS ROUTES ====================

@app.route('/api/events', methods=['GET'])
def get_events():
    """Get all events"""
    conn = get_db()
    events = conn.execute('SELECT * FROM events ORDER BY date DESC').fetchall()
    conn.close()
    return jsonify([dict(row) for row in events])

@app.route('/api/events/<event_id>', methods=['GET'])
def get_event(event_id):
    """Get single event with checklist"""
    conn = get_db()
    event = conn.execute('SELECT * FROM events WHERE id = ?', (event_id,)).fetchone()
    
    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    
    # Get checklist items with equipment details
    checklist = conn.execute('''
        SELECT ee.*, e.name, e.status as equipment_status
        FROM event_equipment ee
        JOIN equipment e ON ee.equipment_id = e.id
        WHERE ee.event_id = ?
        ORDER BY e.name
    ''', (event_id,)).fetchall()
    
    conn.close()
    
    return jsonify({
        'event': dict(event),
        'checklist': [dict(row) for row in checklist]
    })

@app.route('/api/events', methods=['POST'])
def create_event():
    """Create new event"""
    data = request.json
    name = data.get('name')
    event_type = data.get('type')
    date = data.get('date')
    location = data.get('location', '')
    notes = data.get('notes', '')
    
    if not name or not event_type or not date:
        return jsonify({'error': 'Name, type, and date are required'}), 400
    
    # Generate unique ID
    event_id = 'EV' + str(int(datetime.now().timestamp() * 1000))
    
    conn = get_db()
    conn.execute(
        'INSERT INTO events (id, name, type, date, location, status, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (event_id, name, event_type, date, location, 'PLANNING', notes, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        'id': event_id,
        'name': name,
        'message': 'Event created successfully'
    })

@app.route('/api/events/<event_id>', methods=['PUT'])
def update_event(event_id):
    """Update event details"""
    data = request.json
    
    conn = get_db()
    
    # Build update query dynamically based on provided fields
    fields = []
    values = []
    
    if 'name' in data:
        fields.append('name = ?')
        values.append(data['name'])
    if 'type' in data:
        fields.append('type = ?')
        values.append(data['type'])
    if 'date' in data:
        fields.append('date = ?')
        values.append(data['date'])
    if 'location' in data:
        fields.append('location = ?')
        values.append(data['location'])
    if 'status' in data:
        fields.append('status = ?')
        values.append(data['status'])
    if 'notes' in data:
        fields.append('notes = ?')
        values.append(data['notes'])
    
    if not fields:
        conn.close()
        return jsonify({'error': 'No fields to update'}), 400
    
    values.append(event_id)
    query = f"UPDATE events SET {', '.join(fields)} WHERE id = ?"
    
    conn.execute(query, values)
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Event updated successfully'})

@app.route('/api/events/<event_id>', methods=['DELETE'])
def delete_event(event_id):
    """Delete event and its checklist"""
    conn = get_db()
    conn.execute('DELETE FROM event_equipment WHERE event_id = ?', (event_id,))
    conn.execute('DELETE FROM events WHERE id = ?', (event_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Event deleted successfully'})

@app.route('/api/events/<event_id>/checklist', methods=['POST'])
def add_to_checklist(event_id):
    """Add equipment to event checklist"""
    data = request.json
    equipment_id = data.get('equipment_id')
    
    if not equipment_id:
        return jsonify({'error': 'Equipment ID is required'}), 400
    
    conn = get_db()
    
    # Check if already in checklist
    existing = conn.execute(
        'SELECT id FROM event_equipment WHERE event_id = ? AND equipment_id = ?',
        (event_id, equipment_id)
    ).fetchone()
    
    if existing:
        conn.close()
        return jsonify({'error': 'Equipment already in checklist'}), 400
    
    conn.execute(
        'INSERT INTO event_equipment (event_id, equipment_id) VALUES (?, ?)',
        (event_id, equipment_id)
    )
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Equipment added to checklist'})

@app.route('/api/events/<event_id>/checklist/<int:item_id>', methods=['DELETE'])
def remove_from_checklist(event_id, item_id):
    """Remove equipment from event checklist"""
    conn = get_db()
    conn.execute('DELETE FROM event_equipment WHERE id = ? AND event_id = ?', (item_id, event_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Equipment removed from checklist'})

@app.route('/api/events/<event_id>/checklist/<int:item_id>', methods=['PUT'])
def update_checklist_item(event_id, item_id):
    """Update checklist item (notes, status)"""
    data = request.json
    
    conn = get_db()
    
    fields = []
    values = []
    
    if 'checked_out' in data:
        fields.append('checked_out = ?')
        values.append(1 if data['checked_out'] else 0)
    if 'checked_in' in data:
        fields.append('checked_in = ?')
        values.append(1 if data['checked_in'] else 0)
    if 'notes' in data:
        fields.append('notes = ?')
        values.append(data['notes'])
    
    if not fields:
        conn.close()
        return jsonify({'error': 'No fields to update'}), 400
    
    values.extend([item_id, event_id])
    query = f"UPDATE event_equipment SET {', '.join(fields)} WHERE id = ? AND event_id = ?"
    
    conn.execute(query, values)
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Checklist item updated'})

# ==================== TEMPLATES ROUTES ====================

@app.route('/api/templates', methods=['GET'])
def get_templates():
    """Get all event templates"""
    conn = get_db()
    templates = conn.execute('SELECT * FROM event_templates ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(row) for row in templates])

@app.route('/api/templates/<template_id>', methods=['GET'])
def get_template(template_id):
    """Get template with items"""
    conn = get_db()
    template = conn.execute('SELECT * FROM event_templates WHERE id = ?', (template_id,)).fetchone()
    
    if not template:
        conn.close()
        return jsonify({'error': 'Template not found'}), 404
    
    items = conn.execute(
        'SELECT * FROM template_items WHERE template_id = ?',
        (template_id,)
    ).fetchall()
    
    conn.close()
    
    return jsonify({
        'template': dict(template),
        'items': [dict(row) for row in items]
    })

@app.route('/api/templates', methods=['POST'])
def create_template():
    """Create event template"""
    data = request.json
    name = data.get('name')
    description = data.get('description', '')
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    
    template_id = 'TPL' + str(int(datetime.now().timestamp() * 1000))
    
    conn = get_db()
    conn.execute(
        'INSERT INTO event_templates (id, name, description) VALUES (?, ?, ?)',
        (template_id, name, description)
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        'id': template_id,
        'name': name,
        'message': 'Template created successfully'
    })

# ==================== EXPORT/IMPORT ROUTES ====================

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