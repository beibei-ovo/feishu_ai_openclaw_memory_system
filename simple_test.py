#!/usr/bin/env python3
"""简单测试导入"""

print("Testing imports...")
try:
    import sqlalchemy
    print(f"SQLAlchemy imported: {sqlalchemy.__version__}")
    
    from sqlalchemy import create_engine, Column, String
    from sqlalchemy.orm import DeclarativeBase, sessionmaker
    print("SQLAlchemy components imported")
    
    from app.infrastructure.database import Base, MemoryModel
    print("Database models imported")
    
    print("\nSUCCESS! All imports work correctly.")
    
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()

