import os
import pymongo
from pymongo import MongoClient
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class FileDatabase:
    def __init__(self, connection_string=None):
        """Initialize MongoDB connection"""
        self.connection_string = connection_string or os.getenv('MONGODB_URL')
        self.client = None
        self.db = None
        self.files_collection = None
        self.connect()
    
    def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(self.connection_string)
            self.db = self.client['tg_file_bot']
            self.files_collection = self.db['files']
            
            # Create indexes for better performance
            self.files_collection.create_index([("unique_id", 1), ("hash", 1)])
            self.files_collection.create_index([("created_at", 1)])
            self.files_collection.create_index([("telegram_file_id", 1)])
            
            logger.info("Connected to MongoDB successfully")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    def store_file(self, file_data):
        """Store file information in database"""
        try:
            # Add timestamp
            file_data['created_at'] = datetime.utcnow()
            file_data['expires_at'] = datetime.utcnow() + timedelta(days=30)  # 30-day expiry
            
            result = self.files_collection.insert_one(file_data)
            logger.info(f"Stored file with ID: {result.inserted_id}")
            return result.inserted_id
        except Exception as e:
            logger.error(f"Failed to store file: {e}")
            return None
    
    def get_file(self, unique_id, hash_value):
        """Retrieve file information by ID and hash"""
        try:
            file_doc = self.files_collection.find_one({
                "unique_id": unique_id,
                "hash": hash_value,
                "expires_at": {"$gt": datetime.utcnow()}
            })
            return file_doc
        except Exception as e:
            logger.error(f"Failed to retrieve file: {e}")
            return None
    
    def get_user_files(self, user_id, limit=10):
        """Get user's recent files"""
        try:
            files = self.files_collection.find({
                "user_id": user_id
            }).sort("created_at", -1).limit(limit)
            return list(files)
        except Exception as e:
            logger.error(f"Failed to get user files: {e}")
            return []
    
    def cleanup_expired_files(self):
        """Remove expired files"""
        try:
            result = self.files_collection.delete_many({
                "expires_at": {"$lt": datetime.utcnow()}
            })
            logger.info(f"Cleaned up {result.deleted_count} expired files")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Failed to cleanup files: {e}")
            return 0
    
    def get_stats(self):
        """Get database statistics"""
        try:
            total_files = self.files_collection.count_documents({})
            active_files = self.files_collection.count_documents({
                "expires_at": {"$gt": datetime.utcnow()}
            })
            
            # Calculate total size
            pipeline = [
                {"$group": {"_id": None, "total_size": {"$sum": "$file_size"}}}
            ]
            size_result = list(self.files_collection.aggregate(pipeline))
            total_size = size_result[0]['total_size'] if size_result else 0
            
            return {
                "total_files": total_files,
                "active_files": active_files,
                "total_size": total_size
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}

# Global database instance
db = None

def init_database():
    """Initialize database connection"""
    global db
    if not db:
        db = FileDatabase()
    return db

def get_database():
    """Get database instance"""
    global db
    if not db:
        db = init_database()
    return db
