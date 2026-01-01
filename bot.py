import os
import asyncio
import logging
import re
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from typing import Dict, List, Set, Tuple, Optional
import random
import time
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.error import TelegramError

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Set in Render environment variables
PORT = int(os.environ.get("PORT", 8443))
TIMEZONE_OFFSET = "+1"  # UTC+1

# Valid country codes (extend as needed)
VALID_COUNTRY_CODES = {
    '234', '237', '7', '20', '33', '44', '49', '55', '81', '82',
    '86', '91', '92', '93', '94', '98', '212', '213', '216', '218',
    '220', '221', '222', '223', '224', '225', '226', '227', '228',
    '229', '230', '231', '232', '233', '234', '235', '236', '237',
    '238', '239', '240', '241', '242', '243', '244', '245', '246',
    '247', '248', '249', '250', '251', '252', '253', '254', '255',
    '256', '257', '258', '259', '260', '261', '262', '263', '264',
    '265', '266', '267', '268', '269', '290', '291', '297', '298',
    '299', '350', '351', '352', '353', '354', '355', '356', '357',
    '358', '359', '370', '371', '372', '373', '374', '375', '376',
    '377', '378', '379', '380', '381', '382', '383', '385', '386',
    '387', '389', '420', '421', '423', '500', '501', '502', '503',
    '504', '505', '506', '507', '508', '509', '590', '591', '592',
    '593', '594', '595', '596', '597', '598', '599', '670', '672',
    '673', '674', '675', '676', '677', '678', '679', '680', '681',
    '682', '683', '685', '686', '687', '688', '689', '690', '691',
    '692', '850', '852', '853', '855', '856', '880', '886', '960',
    '961', '962', '963', '964', '965', '966', '967', '968', '970',
    '971', '972', '973', '974', '975', '976', '977', '992', '993',
    '994', '995', '996', '998'
}

# ============================================================================
# USER DATA MANAGEMENT
# ============================================================================
class UserData:
    def __init__(self):
        self.operations = {
            'whatsapp': True,      # Check WhatsApp
            'sms': True,           # Check SMS receive
            'combo_mode': False,   # Combo AND mode
            'whatsapp_type': 'all',  # 'all', 'on', 'off'
            'sms_type': 'all'       # 'all', 'on', 'off'
        }
        self.last_activity = datetime.now()
        self.processing = False
    
    def get_operations_display(self):
        """Get human-readable operations status"""
        ops = []
        if self.operations['whatsapp']:
            if self.operations['whatsapp_type'] == 'on':
                ops.append("✅ On WhatsApp")
            elif self.operations['whatsapp_type'] == 'off':
                ops.append("❌ Not on WhatsApp")
            else:
                ops.append("📱 WhatsApp Status")
        
        if self.operations['sms']:
            if self.operations['sms_type'] == 'on':
                ops.append("📨 Can receive SMS")
            elif self.operations['sms_type'] == 'off':
                ops.append("⏳ SMS Try again later")
            else:
                ops.append("📨 SMS Status")
        
        if self.operations['combo_mode'] and len(ops) > 1:
            ops[-1] = f"🔀 COMBO: {' AND '.join(ops)}"
        
        return ops

# Store user data in memory (for production, use Redis/Database)
user_sessions = {}

def get_user_data(user_id: int) -> UserData:
    """Get or create user data"""
    if user_id not in user_sessions:
        user_sessions[user_id] = UserData()
    return user_sessions[user_id]

# ============================================================================
# NUMBER PROCESSING & VALIDATION
# ============================================================================
def normalize_phone_number(number: str) -> Optional[str]:
    """
    Normalize phone number to E.164 format without +
    """
    # Remove all non-digit characters except leading +
    number = number.strip()
    
    # Remove spaces, dashes, parentheses
    number = re.sub(r'[\s\-()]', '', number)
    
    # Handle + prefix
    if number.startswith('+'):
        number = number[1:]
    
    # Remove leading zeros
    number = number.lstrip('0')
    
    # Validate number length
    if len(number) < 8 or len(number) > 15:
        return None
    
    # Extract country code
    for cc in VALID_COUNTRY_CODES:
        if number.startswith(cc):
            # Ensure there's a subscriber number after country code
            if len(number) > len(cc):
                return number
    
    # If no country code matches, assume it's already a national number
    # You might want to add a default country code here
    return number if len(number) >= 10 else None

def extract_numbers_from_text(text: str) -> List[str]:
    """Extract and normalize phone numbers from text"""
    numbers = []
    
    # Split by lines and common delimiters
    lines = text.split('\n')
    for line in lines:
        # Split by comma, semicolon, tab, or space
        parts = re.split(r'[,\s;]+', line.strip())
        for part in parts:
            if part:
                normalized = normalize_phone_number(part)
                if normalized:
                    numbers.append(normalized)
    
    return list(set(numbers))  # Remove duplicates

def extract_numbers_from_file(file_content: bytes, filename: str) -> List[str]:
    """Extract numbers from uploaded file"""
    numbers = []
    
    try:
        if filename.endswith('.txt'):
            text = file_content.decode('utf-8', errors='ignore')
            numbers = extract_numbers_from_text(text)
        
        elif filename.endswith('.csv'):
            text = file_content.decode('utf-8', errors='ignore')
            # Simple CSV parsing - look for numbers in all cells
            lines = text.split('\n')
            for line in lines:
                cells = line.split(',')
                for cell in cells:
                    normalized = normalize_phone_number(cell.strip())
                    if normalized:
                        numbers.append(normalized)
    
    except Exception as e:
        logger.error(f"Error parsing file: {e}")
    
    return list(set(numbers))

# ============================================================================
# SIMULATION FUNCTIONS (Replace with actual API calls)
# ============================================================================
async def check_whatsapp_status(number: str) -> Tuple[bool, str]:
    """
    Simulate WhatsApp check
    In production, replace with actual WhatsApp API
    """
    await asyncio.sleep(0.05)  # Simulate API delay
    
    # Simulation logic (replace with real API)
    last_digit = int(number[-1]) if number[-1].isdigit() else 0
    
    if last_digit % 3 == 0:
        return False, "Not on WhatsApp"
    elif last_digit % 3 == 1:
        return True, "On WhatsApp"
    else:
        return False, "Not on WhatsApp"

async def check_sms_status(number: str) -> Tuple[bool, str, Optional[str]]:
    """
    Simulate SMS receive check
    In production, replace with actual SMS API
    """
    await asyncio.sleep(0.05)  # Simulate API delay
    
    # Simulation logic (replace with real API)
    last_digit = int(number[-1]) if number[-1].isdigit() else 0
    
    if last_digit % 4 == 0:
        return True, "Can receive SMS", None
    elif last_digit % 4 == 1:
        wait_time = random.randint(1, 15)
        return False, f"Try again in {wait_time} min", f"{wait_time}:00"
    elif last_digit % 4 == 2:
        wait_time = random.randint(16, 30)
        return False, f"Try again in {wait_time} min", f"{wait_time}:00"
    else:
        return False, "Cannot receive SMS", None

async def process_numbers(
    numbers: List[str],
    user_data: UserData
) -> Tuple[Dict[str, List], Dict[str, int]]:
    """
    Process numbers based on user's operation settings
    """
    results = {
        'whatsapp_on': [],
        'whatsapp_off': [],
        'sms_on': [],
        'sms_off': [],
        'combo': [],
        'processed': []
    }
    
    stats = {
        'total': len(numbers),
        'whatsapp_on': 0,
        'whatsapp_off': 0,
        'sms_on': 0,
        'sms_off': 0,
        'combo': 0
    }
    
    # Process in batches to avoid blocking
    batch_size = 10
    for i in range(0, len(numbers), batch_size):
        batch = numbers[i:i + batch_size]
        batch_tasks = []
        
        for number in batch:
            # Create tasks based on selected operations
            task_info = {'number': number}
            
            if user_data.operations['whatsapp']:
                task_info['whatsapp_task'] = asyncio.create_task(check_whatsapp_status(number))
            
            if user_data.operations['sms']:
                task_info['sms_task'] = asyncio.create_task(check_sms_status(number))
            
            batch_tasks.append(task_info)
        
        # Wait for all tasks in batch
        for task_info in batch_tasks:
            number = task_info['number']
            whatsapp_result = None
            sms_result = None
            
            if 'whatsapp_task' in task_info:
                whatsapp_status, whatsapp_msg = await task_info['whatsapp_task']
                whatsapp_result = {
                    'status': whatsapp_status,
                    'message': whatsapp_msg
                }
            
            if 'sms_task' in task_info:
                sms_status, sms_msg, sms_wait = await task_info['sms_task']
                sms_result = {
                    'status': sms_status,
                    'message': sms_msg,
                    'wait_time': sms_wait
                }
            
            # Apply filters
            whatsapp_match = True
            sms_match = True
            
            if user_data.operations['whatsapp']:
                if user_data.operations['whatsapp_type'] == 'on':
                    whatsapp_match = whatsapp_result['status'] if whatsapp_result else False
                elif user_data.operations['whatsapp_type'] == 'off':
                    whatsapp_match = not whatsapp_result['status'] if whatsapp_result else False
            
            if user_data.operations['sms']:
                if user_data.operations['sms_type'] == 'on':
                    sms_match = sms_result['status'] if sms_result else False
                elif user_data.operations['sms_type'] == 'off':
                    sms_match = not sms_result['status'] if sms_result else False
            
            # Check combo condition
            if user_data.operations['combo_mode']:
                if whatsapp_match and sms_match:
                    results['combo'].append(number)
                    stats['combo'] += 1
            else:
                # Individual results
                if whatsapp_match and user_data.operations['whatsapp']:
                    if whatsapp_result and whatsapp_result['status']:
                        results['whatsapp_on'].append(number)
                        stats['whatsapp_on'] += 1
                    else:
                        results['whatsapp_off'].append(number)
                        stats['whatsapp_off'] += 1
                
                if sms_match and user_data.operations['sms']:
                    if sms_result and sms_result['status']:
                        results['sms_on'].append(number)
                        stats['sms_on'] += 1
                    else:
                        results['sms_off'].append(number)
                        stats['sms_off'] += 1
            
            # Store processed result
            results['processed'].append({
                'number': number,
                'whatsapp': whatsapp_result,
                'sms': sms_result
            })
        
        # Small delay between batches
        if i + batch_size < len(numbers):
            await asyncio.sleep(0.1)
    
    return results, stats

def generate_result_file(results: Dict, user_data: UserData) -> BytesIO:
    """
    Generate result file based on operations
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if user_data.operations['combo_mode']:
        filename = f"combo_results_{timestamp}.txt"
        content = "=== COMBO RESULTS ===\n"
        content += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC{TIMEZONE_OFFSET})\n"
        content += f"Operations: {' AND '.join(user_data.get_operations_display())}\n\n"
        
        if results['combo']:
            content += "Numbers matching ALL conditions:\n"
            for number in results['combo']:
                content += f"+{number}\n"
        else:
            content += "No numbers matched all conditions\n"
    
    else:
        filename = f"checking_results_{timestamp}.txt"
        content = "=== CHECKING RESULTS ===\n"
        content += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC{TIMEZONE_OFFSET})\n\n"
        
        ops_display = user_data.get_operations_display()
        for op in ops_display:
            content += f"{op}\n"
        content += "\n"
        
        if user_data.operations['whatsapp']:
            if results['whatsapp_on']:
                content += "✅ ON WHATSAPP:\n"
                for number in results['whatsapp_on']:
                    content += f"+{number}\n"
                content += "\n"
            
            if results['whatsapp_off']:
                content += "❌ NOT ON WHATSAPP:\n"
                for number in results['whatsapp_off']:
                    content += f"+{number}\n"
                content += "\n"
        
        if user_data.operations['sms']:
            if results['sms_on']:
                content += "📨 CAN RECEIVE SMS:\n"
                for number in results['sms_on']:
                    content += f"+{number}\n"
                content += "\n"
            
            if results['sms_off']:
                content += "⏳ SMS TRY AGAIN LATER:\n"
                for number in results['sms_off']:
                    content += f"+{number}\n"
    
    # Convert to bytes
    file_buffer = BytesIO(content.encode('utf-8'))
    file_buffer.name = filename
    
    return file_buffer

# ============================================================================
# TELEGRAM BOT HANDLERS
# ============================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    welcome_message = f"""
👋 Welcome {user.first_name} to Number Validator Bot!

I can check phone numbers for:
✅ WhatsApp status (On/Off WhatsApp)
✅ SMS receive status (Can receive SMS/Try again later)
✅ Combo checks (Multiple conditions simultaneously)

📤 Send me:
1. List of numbers (one per line)
2. .txt file with numbers
3. .csv file with numbers

📞 Format: +2348123456789 or 2348123456789
🌍 Country codes allowed: +1, +234, +237, +7, +91, etc.

⚙️ Commands:
/setop - Set checking operations
/status - Show current settings
/help - Show help
/about - About this bot

⏰ Timezone: UTC{TIMEZONE_OFFSET}
"""
    
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
📚 **HELP GUIDE**

**1. Sending Numbers:**
- Paste numbers (one per line)
- Upload .txt or .csv file
- Format: +2348123456789 or 2348123456789

**2. Setting Operations (/setop):**
- Choose what to check:
  1️⃣ On WhatsApp only
  2️⃣ Not on WhatsApp only
  3️⃣ Can receive SMS only
  4️⃣ SMS try again later
  5️⃣ Combo mode (add 'c' for AND combination)

**3. Examples:**
- "1" = Check only WhatsApp users
- "1,3" = Check WhatsApp + SMS receivers
- "2,4,c" = COMBO: Not on WhatsApp AND SMS try later

**4. Results:**
- Files are auto-generated
- Includes timestamp (UTC{TIMEZONE_OFFSET})
- Shows statistics
- Removes duplicates

**5. Notes:**
- Processing may take time for large files
- Maximum 1000 numbers per batch
- Results are not stored
"""
    await update.message.reply_text(help_text)

async def setop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setop command to set operations"""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    keyboard = [
        [
            InlineKeyboardButton("1️⃣ WhatsApp On", callback_data="op_1"),
            InlineKeyboardButton("2️⃣ WhatsApp Off", callback_data="op_2")
        ],
        [
            InlineKeyboardButton("3️⃣ SMS On", callback_data="op_3"),
            InlineKeyboardButton("4️⃣ SMS Off", callback_data="op_4")
        ],
        [
            InlineKeyboardButton("🔀 Enable Combo", callback_data="op_combo"),
            InlineKeyboardButton("✅ Apply Settings", callback_data="op_apply")
        ],
        [
            InlineKeyboardButton("🔄 Reset to Default", callback_data="op_reset")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    ops_display = "\n".join([f"• {op}" for op in user_data.get_operations_display()])
    
    message = f"""
⚙️ **SET OPERATIONS**

Current settings:
{ops_display}

**Select operations:**
1️⃣ - On WhatsApp only
2️⃣ - Not on WhatsApp only
3️⃣ - Can receive SMS only
4️⃣ - SMS try again later

**Combo Mode:** {'✅ Enabled' if user_data.operations['combo_mode'] else '❌ Disabled'}
• Combo requires 2+ operations
• Numbers must match ALL conditions

**Or type manually:** "1,3" or "2,4,c"
"""
    
    await update.message.reply_text(message, reply_markup=reply_markup)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    ops_display = "\n".join([f"• {op}" for op in user_data.get_operations_display()])
    
    status_message = f"""
📊 **BOT STATUS**

**Your Settings:**
{ops_display}

**Timezone:** UTC{TIMEZONE_OFFSET}
**Last Activity:** {user_data.last_activity.strftime('%Y-%m-%d %H:%M:%S')}

**Ready to receive:**
• List of numbers (paste)
• .txt files
• .csv files

Use /setop to change operations
"""
    
    await update.message.reply_text(status_message)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /about command"""
    about_text = """
🤖 **Number Validator Bot**

**Version:** 2.0.0
**Timezone:** UTC{TIMEZONE_OFFSET}

**Features:**
• WhatsApp status checking
• SMS receive capability testing
• Combo mode (multiple conditions)
• File generation (TXT)
• Batch processing
• Duplicate removal

**Country Codes Supported:**
All major country codes (200+)
Format: +[country code][number]

**Privacy:**
• Numbers are processed temporarily
• No data storage
• Results auto-delete after sending

**For support:** Contact developer
"""
    await update.message.reply_text(about_text)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user_data = get_user_data(user_data)
    
    data = query.data
    
    if data == "op_1":
        user_data.operations['whatsapp'] = True
        user_data.operations['whatsapp_type'] = 'on'
        user_data.operations['sms'] = False
        await query.edit_message_text("✅ Set: On WhatsApp only\nClick 'Apply Settings' when done")
    
    elif data == "op_2":
        user_data.operations['whatsapp'] = True
        user_data.operations['whatsapp_type'] = 'off'
        user_data.operations['sms'] = False
        await query.edit_message_text("✅ Set: Not on WhatsApp only\nClick 'Apply Settings' when done")
    
    elif data == "op_3":
        user_data.operations['whatsapp'] = False
        user_data.operations['sms'] = True
        user_data.operations['sms_type'] = 'on'
        await query.edit_message_text("✅ Set: Can receive SMS only\nClick 'Apply Settings' when done")
    
    elif data == "op_4":
        user_data.operations['whatsapp'] = False
        user_data.operations['sms'] = True
        user_data.operations['sms_type'] = 'off'
        await query.edit_message_text("✅ Set: SMS try again later\nClick 'Apply Settings' when done")
    
    elif data == "op_combo":
        user_data.operations['combo_mode'] = not user_data.operations['combo_mode']
        status = "✅ Enabled" if user_data.operations['combo_mode'] else "❌ Disabled"
        await query.edit_message_text(f"Combo Mode: {status}\nSelect operations first, then apply")
    
    elif data == "op_apply":
        ops_display = "\n".join(user_data.get_operations_display())
        await query.edit_message_text(f"""
✅ Settings Applied!

Active operations:
{ops_display}

Ready to receive numbers!
Send list or file now.
        """)
    
    elif data == "op_reset":
        user_data.operations = {
            'whatsapp': True,
            'sms': True,
            'combo_mode': False,
            'whatsapp_type': 'all',
            'sms_type': 'all'
        }
        await query.edit_message_text("🔄 Reset to default settings\nBoth WhatsApp and SMS checking enabled")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages containing numbers"""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data.processing:
        await update.message.reply_text("⏳ Please wait, still processing previous request...")
        return
    
    # Check if this is a manual operation setting
    text = update.message.text.strip()
    if re.match(r'^[1-4,c\s]+$', text.replace(',', '')):
        # It's an operation setting
        await handle_manual_operation(update, text)
        return
    
    user_data.processing = True
    user_data.last_activity = datetime.now()
    
    try:
        # Extract numbers from text
        numbers = extract_numbers_from_text(text)
        
        if not numbers:
            await update.message.reply_text("""
❌ No valid phone numbers found!

Please send:
• Numbers with country codes (e.g., +2348123456789)
• One number per line
• Or upload .txt/.csv file

Format examples:
+2348123456789
2348123456789
+14441234567
""")
            user_data.processing = False
            return
        
        if len(numbers) > 1000:
            await update.message.reply_text("⚠️ Too many numbers! Maximum is 1000. Sending first 1000...")
            numbers = numbers[:1000]
        
        # Send processing message
        ops_display = " + ".join(user_data.get_operations_display())
        process_msg = await update.message.reply_text(
            f"📊 Processing {len(numbers)} numbers...\n"
            f"🔍 Checking: {ops_display}\n"
            f"⏳ Estimated time: {len(numbers) * 0.2:.0f} seconds...\n"
            f"🕐 Timezone: UTC{TIMEZONE_OFFSET}"
        )
        
        # Process numbers
        results, stats = await process_numbers(numbers, user_data)
        
        # Generate and send file
        file_buffer = generate_result_file(results, user_data)
        
        # Update processing message
        stats_text = f"""
✅ Processing Complete!

📈 Statistics:
• Total numbers: {stats['total']}
• WhatsApp On: {stats['whatsapp_on']}
• WhatsApp Off: {stats['whatsapp_off']}
• SMS Can Receive: {stats['sms_on']}
• SMS Try Later: {stats['sms_off']}
• Combo Matches: {stats['combo']}

📁 Sending results file...
"""
        
        await process_msg.edit_text(stats_text)
        
        # Send file
        await update.message.reply_document(
            document=file_buffer,
            caption=f"Results - UTC{TIMEZONE_OFFSET}"
        )
        
    except Exception as e:
        logger.error(f"Error processing text: {e}")
        await update.message.reply_text(f"❌ Error processing numbers: {str(e)}")
    
    finally:
        user_data.processing = False

async def handle_manual_operation(update: Update, text: str):
    """Handle manual operation setting via text"""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    parts = [p.strip() for p in text.split(',')]
    
    # Reset operations
    user_data.operations['whatsapp'] = False
    user_data.operations['sms'] = False
    user_data.operations['combo_mode'] = False
    user_data.operations['whatsapp_type'] = 'all'
    user_data.operations['sms_type'] = 'all'
    
    # Parse operations
    for part in parts:
        if part == '1':
            user_data.operations['whatsapp'] = True
            user_data.operations['whatsapp_type'] = 'on'
        elif part == '2':
            user_data.operations['whatsapp'] = True
            user_data.operations['whatsapp_type'] = 'off'
        elif part == '3':
            user_data.operations['sms'] = True
            user_data.operations['sms_type'] = 'on'
        elif part == '4':
            user_data.operations['sms'] = True
            user_data.operations['sms_type'] = 'off'
        elif part.lower() == 'c':
            user_data.operations['combo_mode'] = True
    
    ops_display = "\n".join(user_data.get_operations_display())
    
    await update.message.reply_text(f"""
✅ Operations Set!

Active checks:
{ops_display}

Send your numbers now!
Format: +2348123456789 or upload file
""")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads"""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data.processing:
        await update.message.reply_text("⏳ Please wait, still processing previous request...")
        return
    
    user_data.processing = True
    user_data.last_activity = datetime.now()
    
    try:
        document = update.message.document
        file = await document.get_file()
        file_content = await file.download_as_bytearray()
        
        # Check file type
        filename = document.file_name.lower()
        
        if not (filename.endswith('.txt') or filename.endswith('.csv')):
            await update.message.reply_text("❌ Unsupported file type! Please send .txt or .csv files only.")
            user_data.processing = False
            return
        
        # Extract numbers
        numbers = extract_numbers_from_file(file_content, filename)
        
        if not numbers:
            await update.message.reply_text("❌ No valid phone numbers found in the file!")
            user_data.processing = False
            return
        
        if len(numbers) > 1000:
            await update.message.reply_text("⚠️ Large file detected! Processing first 1000 numbers...")
            numbers = numbers[:1000]
        
        # Send processing message
        ops_display = " + ".join(user_data.get_operations_display())
        process_msg = await update.message.reply_text(
            f"📄 File received: {document.file_name}\n"
            f"📊 Found {len(numbers)} numbers\n"
            f"🔍 Checking: {ops_display}\n"
            f"⏳ Processing... This may take a moment\n"
            f"🕐 Timezone: UTC{TIMEZONE_OFFSET}"
        )
        
        # Process numbers
        results, stats = await process_numbers(numbers, user_data)
        
        # Generate and send file
        file_buffer = generate_result_file(results, user_data)
        
        # Update processing message
        stats_text = f"""
✅ File Processing Complete!

📈 Statistics:
• Total numbers: {stats['total']}
• WhatsApp On: {stats['whatsapp_on']}
• WhatsApp Off: {stats['whatsapp_off']}
• SMS Can Receive: {stats['sms_on']}
• SMS Try Later: {stats['sms_off']}
• Combo Matches: {stats['combo']}

📁 Sending results file...
"""
        
        await process_msg.edit_text(stats_text)
        
        # Send file
        await update.message.reply_document(
            document=file_buffer,
            caption=f"Results from {document.file_name} - UTC{TIMEZONE_OFFSET}"
        )
        
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")
    
    finally:
        user_data.processing = False

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again later or contact support."
            )
    except:
        pass

# ============================================================================
# APPLICATION SETUP
# ============================================================================
def main():
    """Start the bot"""
    # Create Application
    application = Application.builder().token(TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setop", setop_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("about", about_command))
    
    # Add callback query handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    if "RENDER" in os.environ:
        # Running on Render
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"https://your-app-name.onrender.com/{TOKEN}"
        )
    else:
        # Running locally
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
