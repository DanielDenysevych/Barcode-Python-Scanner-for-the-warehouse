from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
from flask_cors import CORS
import sqlite3
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
CORS(app)

# Secret key for session management (change this to something unique for your installation)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-for-production'

DATABASE = 'equipment.db'
UPLOAD_FOLDER = 'uploads/photos'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required', 'redirect': '/login'}), 401
        return f(*args, **kwargs)
    return decorated_function


def init_db():
    """Initialize the database with equipment and events tables"""
    conn = get_db()

    # Create users table first
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT DEFAULT 'user',
            created_at TEXT,
            last_login TEXT
        )
    ''')

    # Create default admin user if no users exist
    cursor = conn.execute('SELECT COUNT(*) as count FROM users')
    user_count = cursor.fetchone()['count']
    
    if user_count == 0:
        # Create default admin user: username=admin, password=admin
        admin_hash = generate_password_hash('admin')
        conn.execute(
            'INSERT INTO users (username, password_hash, full_name, role, created_at) VALUES (?, ?, ?, ?, ?)',
            ('admin', admin_hash, 'Administrator', 'admin', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        print("\n" + "="*50)
        print("⚠️  DEFAULT ADMIN USER CREATED")
        print("Username: admin")
        print("Password: admin")
        print("PLEASE CHANGE THIS PASSWORD AFTER FIRST LOGIN!")
        print("="*50 + "\n")

    # Create categories table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            color TEXT DEFAULT '#333333'
        )
    ''')

    # Check if photo column exists in equipment table
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='equipment'")
    table_exists = cursor.fetchone()

    if table_exists:
        # Check columns
        cursor = conn.execute("PRAGMA table_info(equipment)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'photo' not in columns:
            # Add photo column to existing table
            conn.execute('ALTER TABLE equipment ADD COLUMN photo TEXT')

        if 'quantity' not in columns:
            # Add quantity column - default to 1 for existing items
            conn.execute(
                'ALTER TABLE equipment ADD COLUMN quantity INTEGER DEFAULT 1')

        if 'quantity_out' not in columns:
            # Track how many are currently checked out
            conn.execute(
                'ALTER TABLE equipment ADD COLUMN quantity_out INTEGER DEFAULT 0')

        if 'category_id' not in columns:
            # Add category_id column
            conn.execute('ALTER TABLE equipment ADD COLUMN category_id TEXT')
    else:
        # Create equipment table with photo field
        conn.execute('''
            CREATE TABLE equipment (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                location TEXT,
                last_updated TEXT,
                photo TEXT,
                quantity INTEGER DEFAULT 1,
                quantity_out INTEGER DEFAULT 0,
                category_id TEXT,
                FOREIGN KEY (category_id) REFERENCES categories(id)
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
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='template_items'")
    table_exists = cursor.fetchone()

    if table_exists:
        # Check if old schema (has equipment_name column)
        cursor = conn.execute("PRAGMA table_info(template_items)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'equipment_name' in columns and 'equipment_id' not in columns:
            # Drop old table and recreate with new schema
            conn.execute('DROP TABLE template_items')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS template_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id TEXT NOT NULL,
            equipment_id TEXT NOT NULL,
            FOREIGN KEY (template_id) REFERENCES event_templates(id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(id)
        )
    ''')

    # Equipment history table - tracks all check-ins and check-outs
    conn.execute('''
        CREATE TABLE IF NOT EXISTS equipment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id TEXT NOT NULL,
            action TEXT NOT NULL,
            event_id TEXT,
            event_name TEXT,
            location TEXT,
            scanned_by TEXT,
            timestamp TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id),
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    ''')

    conn.commit()
    conn.close()


# ==================== AUTHENTICATION ROUTES ====================

@app.route('/login')
def login_page():
    """Render login page"""
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def login():
    """Handle user login"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE username = ?', (username,)
    ).fetchone()
    conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        # Login successful
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['full_name'] = user['full_name']
        session['role'] = user['role']
        
        # Update last login
        conn = get_db()
        conn.execute(
            'UPDATE users SET last_login = ? WHERE id = ?',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user['id'])
        )
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'user': {
                'username': user['username'],
                'full_name': user['full_name'],
                'role': user['role']
            }
        })
    else:
        return jsonify({'error': 'Invalid username or password'}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    """Handle user logout"""
    session.clear()
    return jsonify({'success': True})


@app.route('/api/current-user', methods=['GET'])
def current_user():
    """Get current logged-in user info"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    return jsonify({
        'user_id': session['user_id'],
        'username': session['username'],
        'full_name': session['full_name'],
        'role': session['role']
    })


@login_required
@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all users (admin only in future)"""
    conn = get_db()
    users = conn.execute(
        'SELECT id, username, full_name, role, created_at, last_login FROM users ORDER BY username'
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in users])


@login_required
@app.route('/api/users', methods=['POST'])
def create_user():
    """Create new user"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    full_name = data.get('full_name', '')
    role = data.get('role', 'user')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    if len(password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters'}), 400
    
    password_hash = generate_password_hash(password)
    
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO users (username, password_hash, full_name, role, created_at) VALUES (?, ?, ?, ?, ?)',
            (username, password_hash, full_name, role, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'User created successfully'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Username already exists'}), 400


@login_required
@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """Update user information"""
    data = request.json
    conn = get_db()
    
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    # Build update query
    updates = []
    values = []
    
    if 'full_name' in data:
        updates.append('full_name = ?')
        values.append(data['full_name'])
    
    if 'role' in data:
        updates.append('role = ?')
        values.append(data['role'])
    
    if 'password' in data and data['password']:
        if len(data['password']) < 4:
            conn.close()
            return jsonify({'error': 'Password must be at least 4 characters'}), 400
        updates.append('password_hash = ?')
        values.append(generate_password_hash(data['password']))
    
    if not updates:
        conn.close()
        return jsonify({'error': 'No fields to update'}), 400
    
    values.append(user_id)
    query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    
    conn.execute(query, values)
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'User updated successfully'})


@login_required
@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """Delete user"""
    # Prevent deleting yourself
    if session['user_id'] == user_id:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    conn = get_db()
    
    # Prevent deleting last admin
    current_user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if current_user and current_user['role'] == 'admin':
        admin_count = conn.execute("SELECT COUNT(*) as count FROM users WHERE role = 'admin'").fetchone()['count']
        if admin_count <= 1:
            conn.close()
            return jsonify({'error': 'Cannot delete the last admin user'}), 400
    
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'User deleted successfully'})


@login_required
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/uploads/photos/<filename>')
def uploaded_file(filename):
    """Serve uploaded photos"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ==================== EQUIPMENT ROUTES ====================


@login_required
@app.route('/api/equipment', methods=['GET'])
def get_equipment():
    """Get all equipment with category information"""
    conn = get_db()
    equipment = conn.execute('''
        SELECT e.*, c.name as category_name, c.color as category_color
        FROM equipment e
        LEFT JOIN categories c ON e.category_id = c.id
        ORDER BY e.name
    ''').fetchall()
    conn.close()
    return jsonify([dict(row) for row in equipment])



@login_required
@app.route('/api/equipment', methods=['POST'])
def add_equipment():
    """Add new equipment with optional photo and category"""
    # Handle both form data (with photo) and JSON (without photo)
    if request.content_type and 'multipart/form-data' in request.content_type:
        name = request.form.get('name')
        quantity = request.form.get('quantity', 1, type=int)
        category_id = request.form.get('category_id')
    else:
        data = request.json
        name = data.get('name') if data else None
        quantity = data.get('quantity', 1) if data else 1
        category_id = data.get('category_id') if data else None

    if not name:
        return jsonify({'error': 'Name is required'}), 400

    if quantity < 1:
        quantity = 1

    # Generate unique ID
    equipment_id = 'EQ' + str(int(datetime.now().timestamp() * 1000))

    # Handle photo upload
    photo_path = None
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{equipment_id}.{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            photo_path = filename

    conn = get_db()
    conn.execute(
        'INSERT INTO equipment (id, name, status, location, last_updated, photo, quantity, quantity_out, category_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (equipment_id, name, 'IN', 'Warehouse', datetime.now().strftime(
            '%Y-%m-%d %H:%M:%S'), photo_path, quantity, 0, category_id)
    )
    conn.commit()
    conn.close()

    return jsonify({
        'id': equipment_id,
        'name': name,
        'photo': photo_path,
        'quantity': quantity,
        'category_id': category_id,
        'message': 'Equipment added successfully'
    })


@login_required
@app.route('/api/equipment/<equipment_id>/photo', methods=['POST'])
def update_equipment_photo(equipment_id):
    """Update photo for existing equipment"""
    if 'photo' not in request.files:
        return jsonify({'error': 'No photo provided'}), 400

    file = request.files['photo']
    if not file or not file.filename:
        return jsonify({'error': 'No photo selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: png, jpg, jpeg, gif, webp'}), 400

    conn = get_db()
    equipment = conn.execute(
        'SELECT * FROM equipment WHERE id = ?', (equipment_id,)).fetchone()

    if not equipment:
        conn.close()
        return jsonify({'error': 'Equipment not found'}), 404

    # Delete old photo if exists
    if equipment['photo']:
        old_photo_path = os.path.join(
            app.config['UPLOAD_FOLDER'], equipment['photo'])
        if os.path.exists(old_photo_path):
            os.remove(old_photo_path)

    # Save new photo
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{equipment_id}.{ext}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # Update database
    conn.execute(
        'UPDATE equipment SET photo = ? WHERE id = ?',
        (filename, equipment_id)
    )
    conn.commit()
    conn.close()

    return jsonify({
        'message': 'Photo updated successfully',
        'photo': filename
    })


@login_required
@app.route('/api/equipment/<equipment_id>/photo', methods=['DELETE'])
def delete_equipment_photo(equipment_id):
    """Delete photo for equipment"""
    conn = get_db()
    equipment = conn.execute(
        'SELECT * FROM equipment WHERE id = ?', (equipment_id,)).fetchone()

    if not equipment:
        conn.close()
        return jsonify({'error': 'Equipment not found'}), 404

    # Delete photo file if exists
    if equipment['photo']:
        photo_path = os.path.join(
            app.config['UPLOAD_FOLDER'], equipment['photo'])
        if os.path.exists(photo_path):
            os.remove(photo_path)

    # Update database
    conn.execute(
        'UPDATE equipment SET photo = NULL WHERE id = ?',
        (equipment_id,)
    )
    conn.commit()
    conn.close()

    return jsonify({'message': 'Photo deleted successfully'})




@login_required
@app.route('/api/equipment/<equipment_id>', methods=['PUT'])
def update_equipment(equipment_id):
    """Update equipment details (name, quantity, category)"""
    data = request.json
    conn = get_db()

    equipment = conn.execute(
        'SELECT * FROM equipment WHERE id = ?', (equipment_id,)).fetchone()

    if not equipment:
        conn.close()
        return jsonify({'error': 'Equipment not found'}), 404

    # Prepare update fields
    updates = []
    values = []

    if 'name' in data:
        updates.append('name = ?')
        values.append(data['name'])

    if 'quantity' in data:
        quantity = max(1, int(data['quantity']))
        updates.append('quantity = ?')
        values.append(quantity)

    if 'category_id' in data:
        updates.append('category_id = ?')
        values.append(data['category_id'])

    if not updates:
        conn.close()
        return jsonify({'error': 'No fields to update'}), 400

    # Add last_updated
    updates.append('last_updated = ?')
    values.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # Add equipment_id for WHERE clause
    values.append(equipment_id)

    query = f"UPDATE equipment SET {', '.join(updates)} WHERE id = ?"
    conn.execute(query, values)
    conn.commit()
    conn.close()

    return jsonify({'message': 'Equipment updated successfully'})


@login_required
@app.route('/api/equipment/<equipment_id>', methods=['DELETE'])
def delete_equipment(equipment_id):
    """Delete equipment and its photo"""
    conn = get_db()
    equipment = conn.execute(
        'SELECT * FROM equipment WHERE id = ?', (equipment_id,)).fetchone()

    if equipment:
        # Delete photo file if exists
        if equipment['photo']:
            photo_path = os.path.join(
                app.config['UPLOAD_FOLDER'], equipment['photo'])
            if os.path.exists(photo_path):
                os.remove(photo_path)

    conn.execute('DELETE FROM equipment WHERE id = ?', (equipment_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Equipment deleted successfully'})


@login_required
@app.route('/api/scan', methods=['POST'])
def scan_equipment():
    """Process equipment scan (check in/out) with quantity support"""
    data = request.json
    code = data.get('code')
    location = data.get('location', '')
    event_id = data.get('event_id', '')
    scanned_by = data.get('scanned_by', 'Unknown User')
    quantity = data.get('quantity', 1)  # How many to check in/out
    explicit_action = data.get('action', '')  # Explicit action from frontend

    if not code:
        return jsonify({'error': 'Code is required'}), 400

    conn = get_db()
    equipment = conn.execute(
        'SELECT * FROM equipment WHERE id = ?', (code,)).fetchone()

    if not equipment:
        conn.close()
        return jsonify({'error': 'Equipment not found'}), 404

    # Get event name if event_id provided
    event_name = None
    if event_id:
        event = conn.execute(
            'SELECT name FROM events WHERE id = ?', (event_id,)).fetchone()
        if event:
            event_name = event['name']

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Calculate available and out quantities
    total_qty = equipment['quantity']
    current_out = equipment['quantity_out']
    available = total_qty - current_out

    # Use explicit action from frontend if provided, otherwise determine from status
    if explicit_action == 'CHECK_OUT':
        is_checking_out = True
        action = 'CHECK_OUT'
    elif explicit_action == 'CHECK_IN':
        is_checking_out = False
        action = 'CHECK_IN'
    else:
        # Fallback: determine based on status (for backward compatibility)
        if equipment['status'] == 'IN':
            is_checking_out = True
            action = 'CHECK_OUT'
        elif equipment['status'] == 'OUT':
            is_checking_out = False
            action = 'CHECK_IN'
        else:  # PARTIAL - default to check out if available, check in if nothing available
            if available > 0:
                is_checking_out = True
                action = 'CHECK_OUT'
            else:
                is_checking_out = False
                action = 'CHECK_IN'

    if is_checking_out:
        # Checking OUT
        if quantity > available:
            conn.close()
            return jsonify({'error': f'Only {available} available to check out'}), 400

        new_quantity_out = current_out + quantity

        if new_quantity_out >= total_qty:
            new_status = 'OUT'
            message = f"{equipment['name']} - ALL {total_qty} checked OUT to: {location if location else 'Unknown'}"
        else:
            new_status = 'PARTIAL'
            message = f"{equipment['name']} - {quantity} checked OUT (Total out: {new_quantity_out}/{total_qty}) to: {location if location else 'Unknown'}"

        new_location = location if location else 'Unknown'

        # If event_id provided, mark as checked out in event checklist
        if event_id:
            # Check if equipment is already in event checklist
            existing = conn.execute(
                'SELECT id FROM event_equipment WHERE event_id = ? AND equipment_id = ?',
                (event_id, code)
            ).fetchone()
            
            if existing:
                # Already in checklist, just mark as checked out
                conn.execute(
                    'UPDATE event_equipment SET checked_out = 1 WHERE event_id = ? AND equipment_id = ?',
                    (event_id, code)
                )
            else:
                # Not in checklist yet, add it and mark as checked out
                conn.execute(
                    'INSERT INTO event_equipment (event_id, equipment_id, checked_out, checked_in) VALUES (?, ?, 1, 0)',
                    (event_id, code)
                )

    else:
        # Checking IN
        if quantity > current_out:
            quantity = current_out  # Can't check in more than what's out

        new_quantity_out = current_out - quantity

        if new_quantity_out == 0:
            new_status = 'IN'
            new_location = 'Warehouse'
            message = f"{equipment['name']} - ALL {total_qty} checked IN to warehouse"
        else:
            new_status = 'PARTIAL'
            new_location = equipment['location']  # Keep same location
            message = f"{equipment['name']} - {quantity} checked IN (Still out: {new_quantity_out}/{total_qty})"

        action = 'CHECK_IN'

        # If event_id provided, mark as checked in
        if event_id:
            # Only mark as fully checked in if all are back
            if new_quantity_out == 0:
                conn.execute(
                    'UPDATE event_equipment SET checked_in = 1 WHERE event_id = ? AND equipment_id = ?',
                    (event_id, code)
                )

    # Update equipment status
    conn.execute(
        'UPDATE equipment SET status = ?, location = ?, last_updated = ?, quantity_out = ? WHERE id = ?',
        (new_status, new_location, timestamp, new_quantity_out, code)
    )

    # Log to history
    conn.execute('''
        INSERT INTO equipment_history (equipment_id, action, event_id, event_name, location, scanned_by, timestamp, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (code, action, event_id, event_name, new_location, scanned_by, timestamp, f'Quantity: {quantity}'))

    conn.commit()
    conn.close()

    return jsonify({
        'message': message,
        'equipment': {
            'id': equipment['id'],
            'name': equipment['name'],
            'status': new_status,
            'location': new_location,
            'photo': equipment['photo'],
            'quantity': total_qty,
            'quantity_out': new_quantity_out,
            'quantity_available': total_qty - new_quantity_out
        }
    })


@login_required
@app.route('/api/equipment/<equipment_id>/history', methods=['GET'])
def get_equipment_history(equipment_id):
    """Get history for specific equipment"""
    conn = get_db()
    history = conn.execute('''
        SELECT * FROM equipment_history 
        WHERE equipment_id = ? 
        ORDER BY timestamp DESC
    ''', (equipment_id,)).fetchall()
    conn.close()
    return jsonify([dict(row) for row in history])


@login_required
@app.route('/api/history', methods=['GET'])
def get_all_history():
    """Get all equipment history with optional filters"""
    limit = request.args.get('limit', 50, type=int)
    event_id = request.args.get('event_id', None)

    conn = get_db()

    if event_id:
        history = conn.execute('''
            SELECT h.*, e.name as equipment_name
            FROM equipment_history h
            LEFT JOIN equipment e ON h.equipment_id = e.id
            WHERE h.event_id = ?
            ORDER BY h.timestamp DESC
            LIMIT ?
        ''', (event_id, limit)).fetchall()
    else:
        history = conn.execute('''
            SELECT h.*, e.name as equipment_name
            FROM equipment_history h
            LEFT JOIN equipment e ON h.equipment_id = e.id
            ORDER BY h.timestamp DESC
            LIMIT ?
        ''', (limit,)).fetchall()

    conn.close()
    return jsonify([dict(row) for row in history])


# ==================== CATEGORY ROUTES ====================

@login_required
@app.route('/api/categories', methods=['GET'])
def get_categories():
    """Get all categories"""
    conn = get_db()
    categories = conn.execute(
        'SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(row) for row in categories])


@login_required
@app.route('/api/categories', methods=['POST'])
def create_category():
    """Create new category"""
    data = request.json
    name = data.get('name')
    description = data.get('description', '')
    color = data.get('color', '#333333')

    if not name:
        return jsonify({'error': 'Category name is required'}), 400

    category_id = 'CAT' + str(int(datetime.now().timestamp() * 1000))

    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO categories (id, name, description, color) VALUES (?, ?, ?, ?)',
            (category_id, name, description, color)
        )
        conn.commit()
        conn.close()
        return jsonify({
            'id': category_id,
            'name': name,
            'description': description,
            'color': color,
            'message': 'Category created successfully'
        })
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Category name already exists'}), 400


@login_required
@app.route('/api/categories/<category_id>', methods=['PUT'])
def update_category(category_id):
    """Update category"""
    data = request.json
    conn = get_db()

    category = conn.execute(
        'SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()

    if not category:
        conn.close()
        return jsonify({'error': 'Category not found'}), 404

    name = data.get('name', category['name'])
    description = data.get('description', category['description'])
    color = data.get('color', category['color'])

    try:
        conn.execute(
            'UPDATE categories SET name = ?, description = ?, color = ? WHERE id = ?',
            (name, description, color, category_id)
        )
        conn.commit()
        conn.close()
        return jsonify({'message': 'Category updated successfully'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Category name already exists'}), 400


@login_required
@app.route('/api/categories/<category_id>', methods=['DELETE'])
def delete_category(category_id):
    """Delete category (sets equipment category_id to NULL)"""
    conn = get_db()

    # Check if category exists
    category = conn.execute(
        'SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()

    if not category:
        conn.close()
        return jsonify({'error': 'Category not found'}), 404

    # Remove category from equipment (set to NULL)
    conn.execute(
        'UPDATE equipment SET category_id = NULL WHERE category_id = ?',
        (category_id,)
    )

    # Delete category
    conn.execute('DELETE FROM categories WHERE id = ?', (category_id,))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Category deleted successfully'})


# ==================== EVENTS ROUTES ====================


@login_required
@app.route('/api/events', methods=['GET'])
def get_events():
    """Get all events"""
    conn = get_db()
    events = conn.execute('SELECT * FROM events ORDER BY date DESC').fetchall()
    conn.close()
    return jsonify([dict(row) for row in events])


@login_required
@app.route('/api/events/<event_id>', methods=['GET'])
def get_event(event_id):
    """Get single event with checklist"""
    conn = get_db()
    event = conn.execute(
        'SELECT * FROM events WHERE id = ?', (event_id,)).fetchone()

    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404

    # Get checklist items with equipment details including photos
    checklist = conn.execute('''
        SELECT ee.*, e.name, e.status as equipment_status, e.photo
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


@login_required
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
        (event_id, name, event_type, date, location, 'PLANNING',
         notes, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()

    return jsonify({
        'id': event_id,
        'name': name,
        'message': 'Event created successfully'
    })


@login_required
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


@login_required
@app.route('/api/events/<event_id>', methods=['DELETE'])
def delete_event(event_id):
    """Delete event and its checklist"""
    conn = get_db()
    conn.execute('DELETE FROM event_equipment WHERE event_id = ?', (event_id,))
    conn.execute('DELETE FROM events WHERE id = ?', (event_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Event deleted successfully'})


@login_required
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


@login_required
@app.route('/api/events/<event_id>/checklist/<int:item_id>', methods=['DELETE'])
def remove_from_checklist(event_id, item_id):
    """Remove equipment from event checklist"""
    conn = get_db()
    conn.execute(
        'DELETE FROM event_equipment WHERE id = ? AND event_id = ?', (item_id, event_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Equipment removed from checklist'})


@login_required
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


@login_required
@app.route('/api/templates', methods=['GET'])
def get_templates():
    """Get all event templates"""
    conn = get_db()
    templates = conn.execute(
        'SELECT * FROM event_templates ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(row) for row in templates])


@login_required
@app.route('/api/templates/<template_id>', methods=['GET'])
def get_template(template_id):
    """Get template with items"""
    conn = get_db()
    template = conn.execute(
        'SELECT * FROM event_templates WHERE id = ?', (template_id,)).fetchone()

    if not template:
        conn.close()
        return jsonify({'error': 'Template not found'}), 404

    # Get template items with equipment details
    items = conn.execute('''
        SELECT ti.id, ti.template_id, ti.equipment_id, e.name as equipment_name
        FROM template_items ti
        LEFT JOIN equipment e ON ti.equipment_id = e.id
        WHERE ti.template_id = ?
        ORDER BY e.name
    ''', (template_id,)).fetchall()

    conn.close()

    return jsonify({
        'template': dict(template),
        'items': [dict(row) for row in items]
    })


@login_required
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


@login_required
@app.route('/api/templates/<template_id>/items', methods=['POST'])
def add_template_item(template_id):
    """Add equipment to template"""
    data = request.json
    equipment_id = data.get('equipment_id')

    if not equipment_id:
        return jsonify({'error': 'Equipment ID is required'}), 400

    conn = get_db()

    # Check if already exists
    existing = conn.execute(
        'SELECT id FROM template_items WHERE template_id = ? AND equipment_id = ?',
        (template_id, equipment_id)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'error': 'Equipment already in template'}), 400

    conn.execute(
        'INSERT INTO template_items (template_id, equipment_id) VALUES (?, ?)',
        (template_id, equipment_id)
    )
    conn.commit()
    conn.close()

    return jsonify({'message': 'Equipment added to template'})


@login_required
@app.route('/api/templates/<template_id>/items/<int:item_id>', methods=['DELETE'])
def remove_template_item(template_id, item_id):
    """Remove equipment from template"""
    conn = get_db()
    conn.execute(
        'DELETE FROM template_items WHERE id = ? AND template_id = ?', (item_id, template_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Equipment removed from template'})


@login_required
@app.route('/api/templates/<template_id>', methods=['DELETE'])
def delete_template(template_id):
    """Delete template and its items"""
    conn = get_db()
    conn.execute(
        'DELETE FROM template_items WHERE template_id = ?', (template_id,))
    conn.execute('DELETE FROM event_templates WHERE id = ?', (template_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Template deleted successfully'})


@login_required
@app.route('/api/events/<event_id>/apply-template/<template_id>', methods=['POST'])
def apply_template_to_event(event_id, template_id):
    """Apply template to event - adds all template equipment to event checklist"""
    conn = get_db()

    # Get all items from template
    template_items = conn.execute(
        'SELECT equipment_id FROM template_items WHERE template_id = ?',
        (template_id,)
    ).fetchall()

    added = 0
    for item in template_items:
        equipment_id = item['equipment_id']

        # Check if already in event checklist
        existing = conn.execute(
            'SELECT id FROM event_equipment WHERE event_id = ? AND equipment_id = ?',
            (event_id, equipment_id)
        ).fetchone()

        if not existing:
            conn.execute(
                'INSERT INTO event_equipment (event_id, equipment_id) VALUES (?, ?)',
                (event_id, equipment_id)
            )
            added += 1

    conn.commit()
    conn.close()

    return jsonify({
        'message': f'Template applied: {added} items added to checklist',
        'added': added
    })

# ==================== EXPORT/IMPORT ROUTES ====================


@login_required
@app.route('/api/export', methods=['GET'])
def export_data():
    """Export all equipment data"""
    conn = get_db()
    equipment = conn.execute(
        'SELECT * FROM equipment ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(row) for row in equipment])


@login_required
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
        existing = conn.execute(
            'SELECT id FROM equipment WHERE id = ?', (item['id'],)).fetchone()

        # Get photo value, default to None if not present
        photo = item.get('photo', None)

        if existing:
            # Update existing
            conn.execute(
                'UPDATE equipment SET name = ?, status = ?, location = ?, last_updated = ?, photo = ? WHERE id = ?',
                (item['name'], item['status'], item['location'],
                 item['last_updated'], photo, item['id'])
            )
        else:
            # Insert new
            conn.execute(
                'INSERT INTO equipment (id, name, status, location, last_updated, photo) VALUES (?, ?, ?, ?, ?, ?)',
                (item['id'], item['name'], item['status'],
                 item['location'], item['last_updated'], photo)
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