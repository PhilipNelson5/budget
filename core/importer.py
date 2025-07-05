"""
Core importer logic for processing CSV transactions.
"""

import csv
import re
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Callable
from .models import Transaction, ChildTransaction, DatabaseManager


def evaluate_expression(expression: str) -> Decimal:
    """
    Evaluate a simple arithmetic expression containing numbers, +, -, *, and /.

    Args:
        expression: String like "1+2.3" or "10-3.5+2*3/4"

    Returns:
        Decimal result of the arithmetic expression

    Raises:
        ValueError: If the expression is invalid or contains unsupported operations
    """
    # Remove all whitespace
    expression = expression.replace(" ", "").strip()

    # Validate expression contains only allowed characters
    if not re.match(r"^[\d+*./-]+[\d.]$", expression):
        raise ValueError(
            "Expression must contain only numbers, ., +, -, *, /, and must be a valid arithmetic expression"
        )

    # Split on the operators while preserving them
    parts = re.split(r"([+*/-])", expression)

    if not parts or parts[0] == "":
        raise ValueError("Invalid expression")

    # Wrap the values in "Decimal({value})"
    new_parts = []
    for part in parts:
        if len(part) > 0 and part[0] not in {"+", "-", "*", "/"}:
            new_parts.append(f"Decimal('{part}')")
        else:
            new_parts.append(part)

    expression = " ".join(new_parts)
    return Decimal(eval(expression))


class TransactionImporter:
    """Handles importing transactions from CSV files."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def load_transactions_from_csv(self, csv_path: str) -> List[Transaction]:
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

    def import_transaction(
        self, transaction: Transaction, child_creator: Optional[Callable] = None
    ) -> str | None:
        """
        Import a single transaction and optionally create child transactions.

        Args:
            transaction: The transaction to import
            child_creator: Optional callback function to create child transactions.
                          Should return a list of ChildTransaction objects or None.

        Returns:
            The UUID of the imported parent transaction, or None if duplicate
        """
        # Check if transaction already exists
        if self.db_manager.transaction_exists(transaction):
            return None

        # Insert the transaction
        transaction_id = self.db_manager.insert_parent_transaction(transaction)

        # Create child transactions if callback is provided
        if child_creator:
            children = child_creator(transaction, transaction_id)
            if children:
                for child in children:
                    self.db_manager.insert_child_transaction(child)
                # Mark the parent transaction as split
                self.db_manager.mark_transaction_as_split(transaction_id)

        return transaction_id

    def import_transactions(
        self, transactions: List[Transaction], child_creator: Optional[Callable] = None
    ) -> List[str]:
        """
        Import multiple transactions.

        Args:
            transactions: List of transactions to import
            child_creator: Optional callback function to create child transactions

        Returns:
            List of parent transaction UUIDs
        """
        parent_ids = []

        for transaction in transactions:
            parent_id = self.import_transaction(transaction, child_creator)
            parent_ids.append(parent_id)

        return parent_ids


class ChildTransactionCreator:
    """Helper class for creating child transactions with interactive prompts."""

    @staticmethod
    def interactive_split(
        transaction: Transaction, parent_id: str
    ) -> list[ChildTransaction] | None | str:
        """
        Interactively split a transaction into child transactions.

        Args:
            transaction: The parent transaction
            parent_id: The UUID of the parent transaction

        Returns:
            List of child transactions, None to keep original, empty list to skip, or "CHANGE_CATEGORY" to change category
        """
        print(f"\nTransaction: {transaction.description}")
        print(f"Amount: {transaction.amount}")
        print(f"Original Category: {transaction.category}")

        while True:
            choice = input(
                "\nEnter a new category or:\n"
                "s - Split\n"
                "x - Ignore / Hide\n"
                "[Return] - Keep the category\n"
                "Choice: "
            ).strip()

            if choice == "s":
                return ChildTransactionCreator._create_child_transactions(
                    transaction, parent_id
                )
            elif choice == "":
                return None  # No children, keep original
            elif choice == "x":
                return []  # Empty list means skip
            else:
                return choice  # new category

    @staticmethod
    def _create_child_transactions(
        transaction: Transaction, parent_id: str
    ) -> List[ChildTransaction] | None:
        """Helper method to create child transactions interactively."""
        children = []
        sign = -1 if transaction.amount < 0 else 1
        original_amount = abs(transaction.amount)
        remaining_amount = original_amount

        type = "expense" if transaction.amount < 0 else "income"
        print(f"\nSplitting {type}: {transaction.description}")
        print(f"Total amount: ${abs(transaction.amount)}")

        while abs(remaining_amount) > Decimal(
            "0.01"
        ):  # Use Decimal for precise comparison
            print(f"\nRemaining amount: ${remaining_amount}")

            # Get amount for this child
            while True:
                try:
                    amount_str = input(
                        "Enter amount for this split (or empty for the rest): "
                    ).strip()
                    if amount_str == "":
                        amount = remaining_amount
                    else:
                        # Try to evaluate as arithmetic expression first
                        try:
                            amount = evaluate_expression(amount_str)
                        except ValueError as e:
                            print(e)
                            continue

                    if amount > abs(remaining_amount):
                        print(
                            f"Amount cannot exceed remaining amount (${abs(remaining_amount)})."
                        )
                        continue

                    break  # amount is good
                except (ValueError, InvalidOperation):
                    print(
                        "Invalid amount. Please enter a valid number or expression (e.g., '1+2.3')."
                    )

            # Get category for this child
            category = input("Enter category for this split: ").strip()
            if not category:
                category = transaction.category

            # Create child transaction
            child = ChildTransaction(
                parent_id,
                amount * sign,
                category,
                transaction.description,
                transaction.date,
            )
            children.append(child)

            remaining_amount -= amount

            if abs(remaining_amount) <= Decimal("0.01"):
                break

        # If no children were created, return None to keep original
        if not children:
            return None

        return children
