"""
Core importer logic for processing CSV transactions.
"""

import csv

from .models import ChildTransaction, DatabaseManager, Transaction


class TransactionImporter:
    """Handles importing transactions from CSV files."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def load_transactions_from_csv(self, csv_path: str) -> list[Transaction]:
        """Load transactions from CSV file, filtering out pending transactions."""
        transactions = []

        with open(csv_path, "r", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            for row in reader:
                # Skip pending transactions
                if row.get("Is Pending", "No").lower() == "yes":
                    continue

                transaction = Transaction.from_csv_row(row)
                transactions.append(transaction)

        return transactions

    def import_transaction(self, transaction: Transaction) -> str:
        """
        Import a single transaction.

        Args:
            transaction: The transaction to import

        Returns:
            The UUID of the imported parent transaction, or the existing UUID if duplicate
        """
        # Check if transaction already exists
        if self.db_manager.transaction_exists(transaction):
            return self.db_manager.get_duplicate_transaction(transaction)["id"]

        # Insert the transaction
        transaction_id = self.db_manager.insert_parent_transaction(transaction)

        return transaction_id

    def import_child_transaction(self, transaction: ChildTransaction) -> str:
        """
        Import a single transaction.

        Args:
            transaction: The transaction to import

        Returns:
            The UUID of the imported parent transaction, or the existing UUID if duplicate
        """
        return self.db_manager.insert_child_transaction(transaction)
