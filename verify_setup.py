import asyncio
import sys

def test_config():
    print("Step 1: Testing Config Loading...")
    try:
        from config import settings
        print("✓ Config loaded successfully!")
        print(f"  - DATABASE_URL: {settings.DATABASE_URL}")
        print(f"  - REDIS_URL: {settings.REDIS_URL}")
        print(f"  - WHOLESALE_API_TOKEN is set: {'Yes' if settings.WHOLESALE_API_TOKEN else 'No'}")
        print(f"  - INTERNAL_API_SECRET_TOKEN is set: {'Yes' if settings.INTERNAL_API_SECRET_TOKEN else 'No'}")
        return True
    except Exception as e:
        print(f"✗ Config loading failed: {e}")
        return False

def test_imports():
    print("\nStep 2: Testing Models & DB Imports...")
    try:
        from database.db import Base, engine, async_session
        from database.models import User, Product, Order, UnmappedPayment
        print("✓ Modules and models imported successfully without compilation/syntax errors!")
        return True
    except Exception as e:
        print(f"✗ Module importing failed: {e}")
        return False

async def test_db_connection():
    print("\nStep 3: Testing Database Connection & Table Creation...")
    from database.db import Base, engine
    # Import models to ensure they are registered on Base.metadata
    from database.models import User, Product, Order, UnmappedPayment
    
    try:
        async with engine.begin() as conn:
            print("  - Attempting to create database tables...")
            await conn.run_sync(Base.metadata.create_all)
        print("✓ Database connection successful! Tables created/verified successfully.")
        return True
    except Exception as e:
        print(f"⚠ Database connection/table creation could not be completed: {e}")
        print("  - Note: This is expected if the Docker PostgreSQL service is not yet running or accessible.")
        print("  - Recommended Action: Run 'sudo docker-compose up -d' or configure docker socket permissions, then re-run verification.")
        return False

async def main():
    success = test_config()
    if not success:
        sys.exit(1)
    
    success = test_imports()
    if not success:
        sys.exit(1)
        
    await test_db_connection()

if __name__ == "__main__":
    asyncio.run(main())
