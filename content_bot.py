import os
import re
import logging
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime
import yaml
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from git import Repo, GitCommandError

# Add at the top with other imports
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Bot is running!')
    
    def log_message(self, format, *args):
        # Silence the log messages
        return

def run_server():
    server_address = ('', int(os.environ.get('PORT', 8080)))
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    httpd.serve_forever()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
CHOOSING_CONTENT_TYPE, ENTERING_TITLE, ENTERING_DESCRIPTION, ENTERING_CONTENT, ENTERING_TAGS, CONFIRM = range(6)

# Repository settings
REPO_PATH = os.environ.get("REPO_PATH", "./my_content_repo")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_URL = os.environ.get("REPO_URL", "")  # Format: https://x-access-token:GITHUB_TOKEN@github.com/username/repo.git

# Content type paths
CONTENT_PATHS = {
    "blog": "src/content/blog",
    "essays": "src/content/essays",
    "aphorisms": "src/content/aphorisms"
}

# Required fields by content type
REQUIRED_FIELDS = {
    "blog": ["title", "date", "description"],
    "essays": ["title", "date", "description", "readTime"],
    "aphorisms": ["content", "date"]
}

class ContentData:
    def __init__(self, content_type: str):
        self.content_type = content_type
        self.title: Optional[str] = None
        self.description: Optional[str] = None
        self.content: Optional[str] = None
        self.tags: List[str] = []
        self.read_time: Optional[int] = None
        self.date = datetime.now().strftime("%Y-%m-%d")
    
    def is_complete(self) -> bool:
        """Check if all required fields for the content type are filled."""
        required = REQUIRED_FIELDS.get(self.content_type, [])
        
        if "title" in required and not self.title:
            return False
        if "description" in required and not self.description:
            return False
        if "content" in required and not self.content:
            return False
        if "readTime" in required and not self.read_time:
            return False
        
        # Content is always required regardless of content type
        if not self.content:
            return False
            
        return True
    
    def create_frontmatter(self) -> str:
        """Generate frontmatter for the content."""
        fm_data = {}
        
        if self.content_type in ["blog", "essays"]:
            fm_data["title"] = self.title
        
        if self.content_type == "aphorisms":
            fm_data["content"] = self.content
        
        fm_data["date"] = self.date
        
        if self.description and self.content_type in ["blog", "essays"]:
            fm_data["description"] = self.description
        
        if self.read_time and self.content_type == "essays":
            fm_data["readTime"] = self.read_time
        
        if self.tags:
            fm_data["tags"] = self.tags
        
        # Convert to YAML
        frontmatter = yaml.dump(fm_data, default_flow_style=False)
        return f"---\n{frontmatter}---"
    
    def generate_filename(self) -> str:
        """Generate an appropriate filename for the content."""
        if self.content_type in ["blog", "essays"]:
            # Create slug from title
            slug = self.title.lower()
            # Replace spaces with dashes and remove special characters
            slug = re.sub(r'[^a-z0-9\s-]', '', slug)
            slug = re.sub(r'\s+', '-', slug)
            return f"{slug}.md"
        elif self.content_type == "aphorisms":
            # Create slug from first few words of content
            first_words = ' '.join(self.content.split()[:3])
            slug = first_words.lower()
            slug = re.sub(r'[^a-z0-9\s-]', '', slug)
            slug = re.sub(r'\s+', '-', slug)
            return f"{slug}.md"
        
        # Default fallback
        return f"content-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    
    def create_file_content(self) -> str:
        """Create the full content for the file."""
        frontmatter = self.create_frontmatter()
        
        if self.content_type == "aphorisms":
            # For aphorisms, the content is already in the frontmatter
            return frontmatter
        else:
            # For blog and essays, add the content after frontmatter
            # Determine if it's MDX based on content
            is_mdx = "<" in self.content and ">" in self.content
            
            if is_mdx:
                file_content = f"{frontmatter}\n\nimport Summary from '../../components/Summary.astro';\nimport 'uno.css';\n\n{self.content}"
            else:
                file_content = f"{frontmatter}\n\n{self.content}"
            
            return file_content

    def get_file_extension(self) -> str:
        """Determine the appropriate file extension."""
        # Check if content contains JSX/React components
        if "<" in self.content and ">" in self.content and self.content_type != "aphorisms":
            return "mdx"
        return "md"
    
    def get_full_filename(self) -> str:
        """Get the full filename with appropriate extension."""
        base_filename = self.generate_filename()
        # Replace extension
        base_name = os.path.splitext(base_filename)[0]
        return f"{base_name}.{self.get_file_extension()}"

# Git operations
def setup_repo():
    """Set up the repository if it doesn't exist."""
    if not os.path.exists(REPO_PATH):
        # Clone the repository
        if GITHUB_TOKEN and REPO_URL:
            repo_url_with_token = REPO_URL.replace("GITHUB_TOKEN", GITHUB_TOKEN)
            Repo.clone_from(repo_url_with_token, REPO_PATH)
        else:
            raise ValueError("Repository doesn't exist and credentials for cloning not provided")
    
    return Repo(REPO_PATH)

def commit_and_push(repo, file_path: str, commit_message: str) -> bool:
    """Commit changes to the repository and push to remote."""
    try:
        # Pull latest changes
        origin = repo.remote(name="origin")
        origin.pull()
        
        # Add file
        repo.git.add(file_path)
        
        # Commit
        repo.git.commit(m=commit_message)
        
        # Push
        if GITHUB_TOKEN:
            origin.push()
        
        return True
    except GitCommandError as e:
        logger.error(f"Git error: {e}")
        return False

# Telegram bot functions
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "👋 Welcome to the Content Management Bot!\n\n"
        "Use /new to create new content for your website."
    )

async def new_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the content creation process."""
    keyboard = [
        [
            InlineKeyboardButton("Blog Post", callback_data="blog"),
            InlineKeyboardButton("Essay", callback_data="essays"),
        ],
        [InlineKeyboardButton("Aphorism", callback_data="aphorisms")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "What type of content would you like to create?",
        reply_markup=reply_markup,
    )
    return CHOOSING_CONTENT_TYPE

async def content_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the content type choice."""
    query = update.callback_query
    await query.answer()
    
    content_type = query.data
    context.user_data["content_data"] = ContentData(content_type)
    
    if content_type == "aphorisms":
        await query.edit_message_text(
            f"You've chosen to create an aphorism. Please enter your aphorism text:"
        )
        return ENTERING_CONTENT
    else:
        await query.edit_message_text(
            f"You've chosen to create a {content_type} post. Please enter the title:"
        )
        return ENTERING_TITLE

async def title_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the title entry."""
    content_data = context.user_data.get("content_data")
    content_data.title = update.message.text
    
    await update.message.reply_text(
        f"Title: {content_data.title}\n\nNow, please enter a description:"
    )
    return ENTERING_DESCRIPTION

async def description_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the description entry."""
    content_data = context.user_data.get("content_data")
    content_data.description = update.message.text
    
    if content_data.content_type == "essays":
        await update.message.reply_text(
            f"Description saved. Please enter estimated read time in minutes (just the number):"
        )
        return ENTERING_READ_TIME
    
    await update.message.reply_text(
        f"Description saved. Now please enter the main content of your {content_data.content_type}:"
    )
    return ENTERING_CONTENT

async def read_time_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the read time entry for essays."""
    content_data = context.user_data.get("content_data")
    try:
        content_data.read_time = int(update.message.text)
        await update.message.reply_text(
            f"Read time set to {content_data.read_time} minutes. Now please enter the main content of your essay:"
        )
        return ENTERING_CONTENT
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid number for read time:"
        )
        return ENTERING_READ_TIME

async def content_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the main content entry."""
    content_data = context.user_data.get("content_data")
    content_data.content = update.message.text
    
    await update.message.reply_text(
        "Content saved. Please enter tags as comma-separated values (or type 'skip' to skip):"
    )
    return ENTERING_TAGS

async def tags_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle tags entry."""
    content_data = context.user_data.get("content_data")
    
    if update.message.text.lower() != "skip":
        content_data.tags = [tag.strip() for tag in update.message.text.split(",")]
    
    # Prepare confirmation message
    confirmation = f"Content Type: {content_data.content_type}\n"
    
    if content_data.title:
        confirmation += f"Title: {content_data.title}\n"
    
    if content_data.description:
        confirmation += f"Description: {content_data.description}\n"
    
    if content_data.read_time:
        confirmation += f"Read Time: {content_data.read_time} minutes\n"
    
    if content_data.tags:
        confirmation += f"Tags: {', '.join(content_data.tags)}\n"
    
    # Show beginning of content
    content_preview = content_data.content
    if len(content_preview) > 100:
        content_preview = content_preview[:100] + "..."
    
    confirmation += f"\nContent Preview: {content_preview}\n"
    
    keyboard = [
        [
            InlineKeyboardButton("Confirm", callback_data="confirm"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Please confirm your submission:\n\n{confirmation}",
        reply_markup=reply_markup,
    )
    return CONFIRM

async def confirm_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the confirmation of content submission."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("Content creation canceled.")
        return ConversationHandler.END
    
    # Process and save the content
    content_data = context.user_data.get("content_data")
    
    try:
        # Setup repository
        repo = setup_repo()
        
        # Create directory if it doesn't exist
        content_dir = os.path.join(REPO_PATH, CONTENT_PATHS[content_data.content_type])
        os.makedirs(content_dir, exist_ok=True)
        
        # Create file
        filename = content_data.get_full_filename()
        file_path = os.path.join(content_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content_data.create_file_content())
        
        # Commit and push
        commit_message = f"Add {content_data.content_type}: {filename}"
        if commit_and_push(repo, file_path, commit_message):
            await query.edit_message_text(
                f"✅ Content saved and pushed to repository!\nFile: {filename}"
            )
        else:
            await query.edit_message_text(
                f"✅ Content saved locally, but there was an issue pushing to the repository.\nFile: {filename}"
            )
    
    except Exception as e:
        logger.error(f"Error saving content: {e}")
        await query.edit_message_text(
            f"❌ There was an error saving your content: {str(e)}"
        )
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text("Content creation canceled.")
    return ConversationHandler.END

def main() -> None:
    """Run the bot."""
    # Create the Application
    application = Application.builder().token(os.environ.get("TELEGRAM_TOKEN", "")).build()

    # Add conversation handler for content creation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("new", new_content)],
        states={
            CHOOSING_CONTENT_TYPE: [CallbackQueryHandler(content_type_chosen)],
            ENTERING_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, title_entered)],
            ENTERING_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_entered)],
            ENTERING_READ_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, read_time_entered)],
            ENTERING_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, content_entered)],
            ENTERING_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, tags_entered)],
            CONFIRM: [CallbackQueryHandler(confirm_submission)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))

    # Run the bot
    application.run_polling()

if __name__ == "__main__":
        # Start HTTP server in a separate thread
    threading.Thread(target=run_server, daemon=True).start()
    # Start the bot
    main()
