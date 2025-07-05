"""
Database models for transaction importer.
"""

import sqlite3
import uuid
from decimal import Decimal


class Transaction:
    """Represents a transaction from the CSV file."""

    def __init__(
        self,
        date: str,
        description: str,
        institution: str,
        account: str,
        category: str,
        is_hidden: bool,
        amount: Decimal,
    ):
        self.date = date
        self.description = description
        self.institution = institution
        self.account = account
        self.category = category
        self.is_hidden = is_hidden
        self.amount = amount

    @classmethod
    def from_csv_row(cls, row: dict) -> "Transaction":
        """Create a Transaction from a CSV row.

        Args:
            row: Dictionary containing CSV row data

        Returns:
            Transaction: New Transaction instance with parsed amount
        """
        return cls(
            date=row["Date"],
            description=row["Description"],
            institution=row["Institution"],
            account=row["Account"],
            category=row["Category"],
            is_hidden=cls._parse_boolean(row["Is Hidden"]),
            amount=cls._parse_amount(row["Amount"]),
        )

    @staticmethod
    def _parse_boolean(value: str) -> bool:
        """Parse a string boolean value to a Python boolean.

        Args:
            value: String value from CSV ('Yes'/'No' or 'True'/'False')

        Returns:
            bool: Parsed boolean value
        """
        return value.lower() in ("yes", "true", "1")

    @staticmethod
    def _parse_amount(amount_str: str) -> Decimal:
        """Parse the amount string to a Decimal.

        Handles formats like:
        - "$123.45" -> 123.45
        - "($123.45)" -> -123.45

        Args:
            amount_str: Amount string from CSV

        Returns:
            Decimal: The parsed amount as a Decimal
        """
        # Remove dollar sign and parentheses
        clean_amount = amount_str.replace("$", "").replace("(", "").replace(")", "")

        # Convert to Decimal
        amount = Decimal(clean_amount)

        # If the original had parentheses, it was negative
        if "(" in amount_str and ")" in amount_str:
            amount = -amount

        return amount


class ChildTransaction:
    """Represents a child transaction that can be split from a parent transaction."""

    def __init__(
        self,
        parent_id: str,
        amount: Decimal,
        category: str,
        description: str,
        date: str,
    ):
        self.parent_id = parent_id
        self.amount = amount
        self.category = category
        self.description = description
        self.date = date


class DatabaseManager:
    """Manages SQLite database operations."""

    def __init__(self, db_path: str = "transactions.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialize the database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create parent transactions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS parent_transactions (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT NOT NULL,
                    institution TEXT NOT NULL,
                    account TEXT NOT NULL,
                    category TEXT,
                    is_hidden INTEGER NOT NULL,
                    is_split INTEGER NOT NULL DEFAULT 0
                )
            """)

            # Create child transactions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS child_transactions (
                    id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT,
                    category TEXT NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES parent_transactions (id)
                )
            """)

            conn.commit()

    def insert_parent_transaction(self, transaction: Transaction) -> str:
        """Insert a parent transaction and return its UUID."""
        transaction_id = str(uuid.uuid4())

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO parent_transactions
                (id, date, description, institution, account, category, is_hidden, is_split, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    transaction_id,
                    transaction.date,
                    transaction.description,
                    transaction.institution,
                    transaction.account,
                    transaction.category,
                    int(transaction.is_hidden),
                    int(transaction.is_split),
                    str(transaction.amount),
                ),
            )
            conn.commit()

        return transaction_id

    def insert_child_transaction(self, child: ChildTransaction) -> str:
        """Insert a child transaction and return its UUID."""
        child_id = str(uuid.uuid4())

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO child_transactions
                (id, parent_id, amount, category, description, date)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    child_id,
                    child.parent_id,
                    str(child.amount),
                    child.category,
                    child.description,
                    child.date,
                ),
            )
            conn.commit()

        return child_id

    def get_parent_transaction(self, transaction_id: str) -> dict | None:
        """Get a parent transaction by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, date, description, institution, account, category, is_hidden, amount, is_split
                FROM parent_transactions WHERE id = ?
            """,
                (transaction_id,),
            )

            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "date": row[1],
                    "description": row[2],
                    "institution": row[3],
                    "account": row[4],
                    "category": row[5],
                    "is_hidden": bool(row[6]),
                    "amount": Decimal(row[7]),
                    "is_split": bool(row[8]),
                }
            return None

    def get_child_transactions(self, parent_id: str) -> list[dict]:
        """Get all child transactions for a parent."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, parent_id, amount, category, description, date
                FROM child_transactions WHERE parent_id = ?
                ORDER BY date
            """,
                (parent_id,),
            )

            return [
                {
                    "id": row[0],
                    "parent_id": row[1],
                    "amount": Decimal(row[2]),
                    "category": row[3],
                    "description": row[4],
                    "date": row[5],
                }
                for row in cursor.fetchall()
            ]

    def get_all_parent_transactions(self, include_hidden: bool = False) -> list[dict]:
        """Get all parent transactions.

        Args:
            include_hidden: Whether to include hidden transactions

        Returns:
            list[dict]: List of transaction dictionaries
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if include_hidden:
                cursor.execute("""
                    SELECT id, date, description, institution, account, category, is_hidden, amount, is_split
                    FROM parent_transactions
                    ORDER BY date DESC
                """)
            else:
                cursor.execute("""
                    SELECT id, date, description, institution, account, category, is_hidden, amount, is_split
                    FROM parent_transactions
                    WHERE is_hidden = 0
                    ORDER BY date DESC
                """)

            return [
                {
                    "id": row[0],
                    "date": row[1],
                    "description": row[2],
                    "institution": row[3],
                    "account": row[4],
                    "category": row[5],
                    "is_hidden": bool(row[6]),
                    "amount": Decimal(row[7]),
                    "is_split": bool(row[8]),
                }
                for row in cursor.fetchall()
            ]

    def transaction_exists(self, transaction: Transaction) -> bool:
        """Check if a transaction already exists in the database.

        Args:
            transaction: The transaction to check

        Returns:
            bool: True if transaction exists, False otherwise
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM parent_transactions
                WHERE date = ? AND description = ? AND institution = ?
                AND account = ? AND amount = ?
            """,
                (
                    transaction.date,
                    transaction.description,
                    transaction.institution,
                    transaction.account,
                    str(transaction.amount),
                ),
            )

            count = cursor.fetchone()[0]
            return count > 0

    def get_transaction(self, transaction: Transaction | str) -> dict | None:
        """Get the existing transaction if it exists.

        Args:
            transaction: The transaction or transaction id to get

        Returns:
            dict | None: The existing transaction data or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            columns = (
                "id,date,amount,description,institution,account",
                "category",
                "is_hidden",
                "is_split",
            )
            if isinstance(transaction, Transaction):
                cursor.execute(
                    f"""
                    SELECT {",".join(columns)}
                    FROM parent_transactions
                    WHERE date = ? AND description = ? AND institution = ?
                    AND account = ? AND amount = ?
                """,
                    (
                        transaction.date,
                        transaction.description,
                        transaction.institution,
                        transaction.account,
                        str(transaction.amount),
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT {",".join(columns)}
                    FROM parent_transactions
                    WHERE id = ?
                """,
                    (transaction,),
                )

            row = cursor.fetchone()
            if row:
                return {col: value for col, value in zip(columns, row)}
            return None

    def mark_transaction_as_split(self, transaction_id: str) -> None:
        """Mark a parent transaction as split.

        Args:
            transaction_id: The UUID of the parent transaction
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE parent_transactions
                SET is_split = 1
                WHERE id = ?
            """,
                (transaction_id,),
            )
            conn.commit()

    def mark_transaction_as_hidden(self, transaction_id: str) -> None:
        """Mark a parent transaction as hidden.

        Args:
            transaction_id: The UUID of the parent transaction
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE parent_transactions
                SET is_hidden = 1
                WHERE id = ?
            """,
                (transaction_id,),
            )
            conn.commit()

    def update_transaction_category(
        self, transaction_id: str, new_category: str
    ) -> None:
        """Update the category of a parent transaction.

        Args:
            transaction_id: The UUID of the parent transaction
            new_category: The new category to set
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE parent_transactions
                SET category = ?
                WHERE id = ?
            """,
                (new_category, transaction_id),
            )
            conn.commit()
