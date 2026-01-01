import logging
import asyncio
import tempfile
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import os
from dotenv import load_dotenv
import phonenumbers

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation
SELECTING_FILTERS, SETTING_RETRY_TIME = range(2)

# Store user data temporarily
user_sessions = {}

class WhatsAppChecker:
    def __init__(self):
        self.checked_numbers = {}  # Format: {number: {"status": "", "last_check": "", "attempts": 0, "next_retry": ""}}
    
    async def check_number(self, phone_number: str) -> str:
        """
        Check if a phone number is on WhatsApp
        Returns: "on_whatsapp", "not_on_whatsapp", or "error"
        """
        try:
            # Clean and validate phone number
            phone_clean = self.clean_phone_number(phone_number)
            if not phone_clean:
                return "invalid"
            
            # Method 1: Using unofficial API (simulated)
            # In production, you'd use: whatsapp-api, pywhatkit, or selenium
            status = await self._check_via_api(phone_clean)
            
            return status
            
        except Exception as e:
            logger.error(f"Error checking {phone_number}: {e}")
            return "error"
    
    def clean_phone_number(self, phone: str) -> str:
        """Clean and format phone number to international format"""
        try:
            # Remove all non-digit characters except plus
            clean = ''.join(c for c in phone if c.isdigit() or c == '+')
            
            # Parse with phonenumbers library
            parsed = phonenumbers.parse(clean, None)
            
            # Format as E.164
            formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            
            return formatted
        except:
            return None
    
    async def _check_via_api(self, phone: str) -> str:
        """
        Actual WhatsApp checking logic
        REPLACE THIS WITH YOUR PREFERRED METHOD:
        
        Options:
        1. whatsapp-chatbot-api (Python library)
        2. Selenium automation (WhatsApp Web)
        3. pywhatkit (unofficial)
        4. Official Business API (paid)
        """
        # Simulated checking - replace with real implementation
        await asyncio.sleep(0.5)  # Simulate API delay
        
        # For demo: Return random status
        # In production, implement actual WhatsApp check here
        import random
        return random.choice(["on_whatsapp", "not_on_whatsapp"])
    
    def update_status(self, phone: str, status: str, retry_hours: int = 24):
        """Update number status and set retry time if needed"""
        now = datetime.now()
        
        if phone not in self.checked_numbers:
            self.checked_numbers[phone] = {
                "status": status,
                "last_check": now,
                "attempts": 1,
                "next_retry": None
            }
        else:
            self.checked_numbers[phone].update({
                "status": status,
                "last_check": now,
                "attempts": self.checked_numbers[phone]["attempts"] + 1
            })
        
        # Set next retry time for failed checks
        if status == "not_on_whatsapp":
            self.checked_numbers[phone]["next_retry"] = now + timedelta(hours=retry_hours)

# Initialize checker
checker = WhatsAppChecker()

# Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    welcome_text = """
🔍 *WhatsApp Number Checker Bot*

I can:
• Check if numbers are on WhatsApp
• Track retry attempts
• Filter by multiple conditions
• Export results as files

*Available Commands:*
/check - Upload numbers to check
/filter - Filter existing results
/status - View checking progress
/export - Export filtered results
/setretry - Set retry interval (default: 24h)

*How to use:*
1. Send /check with numbers or upload a .txt/.csv file
2. I'll check WhatsApp status for each number
3. Use /filter to select which numbers to export
4. Download your filtered results

*Example formats:*
+2348012345678
2348012345678
08012345678
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def check_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start checking process"""
    keyboard = [
        [InlineKeyboardButton("📝 Paste Numbers", callback_data='paste')],
        [InlineKeyboardButton("📁 Upload File", callback_data='upload')],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "How would you like to send numbers?\n\n"
        "You can:\n"
        "1. Paste numbers (one per line or comma-separated)\n"
        "2. Upload .txt or .csv file",
        reply_markup=reply_markup
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded file"""
    if not update.message.document:
        await update.message.reply_text("Please upload a .txt or .csv file")
        return
    
    file = await update.message.document.get_file()
    file_ext = update.message.document.file_name.split('.')[-1].lower()
    
    if file_ext not in ['txt', 'csv']:
        await update.message.reply_text("Only .txt or .csv files are supported")
        return
    
    # Download file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}')
    await file.download_to_drive(temp_file.name)
    
    # Read numbers from file
    try:
        if file_ext == 'txt':
            with open(temp_file.name, 'r') as f:
                numbers = [line.strip() for line in f if line.strip()]
        else:  # csv
            df = pd.read_csv(temp_file.name)
            # Assume numbers are in first column
            numbers = df.iloc[:, 0].astype(str).tolist()
        
        # Clean up
        os.unlink(temp_file.name)
        
        if not numbers:
            await update.message.reply_text("No numbers found in file")
            return
        
        # Store numbers in context
        context.user_data['numbers_to_check'] = numbers
        context.user_data['total_numbers'] = len(numbers)
        
        # Ask for retry time
        await update.message.reply_text(
            f"Found {len(numbers)} numbers. Set retry interval (in hours):\n"
            "Default is 24 hours. Send a number or /skip for default."
        )
        
        return SETTING_RETRY_TIME
        
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await update.message.reply_text("Error processing file. Please try again.")
        return ConversationHandler.END

async def set_retry_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set retry interval and start checking"""
    retry_hours = 24  # default
    
    if update.message.text.lower() != '/skip':
        try:
            retry_hours = int(update.message.text)
            if retry_hours < 1 or retry_hours > 168:  # 1 hour to 1 week
                await update.message.reply_text("Please enter a number between 1 and 168 (hours)")
                return SETTING_RETRY_TIME
        except ValueError:
            await update.message.reply_text("Please enter a valid number or /skip")
            return SETTING_RETRY_TIME
    
    # Start checking process
    numbers = context.user_data.get('numbers_to_check', [])
    total = len(numbers)
    
    if total == 0:
        await update.message.reply_text("No numbers to check")
        return ConversationHandler.END
    
    # Send progress message
    progress_msg = await update.message.reply_text(
        f"🔍 Checking {total} numbers...\n"
        f"Progress: 0/{total} (0%)\n"
        f"Retry interval: {retry_hours} hours"
    )
    
    # Check each number
    results = []
    checked_count = 0
    
    for i, number in enumerate(numbers, 1):
        status = await checker.check_number(number)
        checker.update_status(number, status, retry_hours)
        
        results.append({
            'phone': checker.clean_phone_number(number) or number,
            'status': status,
            'check_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'next_retry': None if status == 'on_whatsapp' else 
                        (datetime.now() + timedelta(hours=retry_hours)).strftime('%Y-%m-%d %H:%M:%S')
        })
        
        checked_count += 1
        
        # Update progress every 10 numbers or 25%
        if i % 10 == 0 or i == total:
            progress = int((i / total) * 100)
            await progress_msg.edit_text(
                f"🔍 Checking {total} numbers...\n"
                f"Progress: {i}/{total} ({progress}%)\n"
                f"✓ On WhatsApp: {len([r for r in results if r['status'] == 'on_whatsapp'])}\n"
                f"✗ Not on WhatsApp: {len([r for r in results if r['status'] == 'not_on_whatsapp'])}"
            )
    
    # Store results
    context.user_data['check_results'] = results
    context.user_data['retry_hours'] = retry_hours
    
    # Send completion message with filter options
    keyboard = [
        [InlineKeyboardButton("📊 View Results", callback_data='view_results')],
        [InlineKeyboardButton("🔍 Filter Numbers", callback_data='filter_numbers')],
        [InlineKeyboardButton("📤 Export All", callback_data='export_all')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Check completed!\n"
        f"Total checked: {total}\n"
        f"On WhatsApp: {len([r for r in results if r['status'] == 'on_whatsapp'])}\n"
        f"Not on WhatsApp: {len([r for r in results if r['status'] == 'not_on_whatsapp'])}\n"
        f"Errors: {len([r for r in results if r['status'] == 'error'])}",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

async def filter_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show filter options"""
    keyboard = [
        [InlineKeyboardButton("✅ On WhatsApp", callback_data='filter_on_whatsapp')],
        [InlineKeyboardButton("❌ Not on WhatsApp", callback_data='filter_not_on_whatsapp')],
        [InlineKeyboardButton("🔄 On Retry After", callback_data='filter_on_retry')],
        [InlineKeyboardButton("⏳ Not on Retry After", callback_data='filter_not_on_retry')],
        [InlineKeyboardButton("🔀 Combined Filters", callback_data='combined_filters')],
        [InlineKeyboardButton("📤 Export Current", callback_data='export_current')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Select filters to apply:\n\n"
        "*Available filters:*\n"
        "• ✅ On WhatsApp\n"
        "• ❌ Not on WhatsApp\n"
        "• 🔄 On Retry After (numbers scheduled for retry)\n"
        "• ⏳ Not on Retry After\n\n"
        "You can combine filters!",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def handle_combined_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle multiple filter selection"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("❌ Not on WhatsApp", callback_data='add_not_whatsapp')],
        [InlineKeyboardButton("⏳ Not on Retry After", callback_data='add_not_retry')],
        [InlineKeyboardButton("✅ On WhatsApp", callback_data='add_on_whatsapp')],
        [InlineKeyboardButton("🔄 On Retry After", callback_data='add_on_retry')],
        [InlineKeyboardButton("➕ AND (Both must be true)", callback_data='logic_and')],
        [InlineKeyboardButton("➕ OR (Either can be true)", callback_data='logic_or')],
        [InlineKeyboardButton("🔍 Apply Filters", callback_data='apply_combined')],
        [InlineKeyboardButton("🔄 Clear All", callback_data='clear_filters')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Initialize filter state if not exists
    if 'filters' not in context.user_data:
        context.user_data['filters'] = []
        context.user_data['filter_logic'] = 'AND'
    
    filters_text = " + ".join(context.user_data['filters']) if context.user_data['filters'] else "None"
    
    await query.edit_message_text(
        f"*Combined Filters Builder*\n\n"
        f"Current filters: {filters_text}\n"
        f"Logic: {context.user_data['filter_logic']}\n\n"
        f"*How to use:*\n"
        f"1. Add filters using buttons\n"
        f"2. Select AND/OR logic\n"
        f"3. Click 'Apply Filters'",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def apply_filters_and_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apply filters and export results"""
    query = update.callback_query
    await query.answer()
    
    # Get results from context
    results = context.user_data.get('check_results', [])
    
    if not results:
        await query.edit_message_text("No results to filter. Please check some numbers first.")
        return
    
    # Apply filters based on user selection
    filtered_results = results
    
    # Example: Apply "not on WhatsApp + not on retry after"
    filters = context.user_data.get('filters', [])
    logic = context.user_data.get('filter_logic', 'AND')
    
    if 'not_on_whatsapp' in filters:
        filtered_results = [r for r in filtered_results if r['status'] == 'not_on_whatsapp']
    
    if 'not_on_retry' in filters:
        filtered_results = [r for r in filtered_results if not r.get('next_retry') or 
                          datetime.strptime(r['next_retry'], '%Y-%m-%d %H:%M:%S') > datetime.now()]
    
    # For AND logic, we already filtered sequentially
    # For OR logic, we'd need different logic
    
    # Create export file
    if filtered_results:
        df = pd.DataFrame(filtered_results)
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as tmp:
            df.to_csv(tmp.name, index=False)
            
            # Send file
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=open(tmp.name, 'rb'),
                filename=f"filtered_numbers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                caption=f"✅ Exported {len(filtered_results)} numbers\n"
                       f"Filters: {' + '.join(filters) if filters else 'All'}"
            )
            
            # Clean up
            os.unlink(tmp.name)
    else:
        await query.edit_message_text("No numbers match your filters.")

async def export_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export all results"""
    results = context.user_data.get('check_results', [])
    
    if not results:
        await update.message.reply_text("No results to export. Please check some numbers first with /check")
        return
    
    # Ask for format
    keyboard = [
        [InlineKeyboardButton("📄 CSV", callback_data='export_csv')],
        [InlineKeyboardButton("📊 Excel", callback_data='export_excel')],
        [InlineKeyboardButton("📝 TXT", callback_data='export_txt')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Select export format:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'filter_numbers':
        await filter_numbers(query.message, context)
    elif data == 'combined_filters':
        await handle_combined_filters(update, context)
    elif data == 'apply_combined':
        await apply_filters_and_export(update, context)
    elif data.startswith('export_'):
        await export_file(query.message, context, data.replace('export_', ''))
    elif data.startswith('add_'):
        # Add filter to list
        if 'filters' not in context.user_data:
            context.user_data['filters'] = []
        
        filter_name = data.replace('add_', '')
        if filter_name not in context.user_data['filters']:
            context.user_data['filters'].append(filter_name)
        
        await handle_combined_filters(update, context)

async def export_file(message, context, format_type='csv'):
    """Export file in specified format"""
    results = context.user_data.get('check_results', [])
    
    if not results:
        await message.reply_text("No results to export")
        return
    
    df = pd.DataFrame(results)
    
    # Create temp file
    if format_type == 'csv':
        suffix = '.csv'
        filename = f"whatsapp_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(filename, index=False)
    elif format_type == 'excel':
        suffix = '.xlsx'
        filename = f"whatsapp_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        df.to_excel(filename, index=False)
    else:  # txt
        suffix = '.txt'
        filename = f"whatsapp_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, 'w') as f:
            for _, row in df.iterrows():
                f.write(f"{row['phone']} - {row['status']}\n")
    
    # Send file
    await message.reply_document(
        document=open(filename, 'rb'),
        filename=filename,
        caption=f"Exported {len(results)} numbers"
    )
    
    # Clean up
    os.unlink(filename)

def main():
    """Start the bot"""
    # Get token from environment variable
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in environment variables")
        print("Get token from @BotFather and add to .env file")
        return
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add conversation handler for checking numbers
    check_conv = ConversationHandler(
        entry_points=[CommandHandler('check', check_numbers)],
        states={
            SETTING_RETRY_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_retry_time)
            ]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )
    
    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(check_conv)
    application.add_handler(CommandHandler('filter', filter_numbers))
    application.add_handler(CommandHandler('export', export_results))
    application.add_handler(CommandHandler('status', start))
    
    # Handle file uploads
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    
    # Handle button clicks
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start bot
    print("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
