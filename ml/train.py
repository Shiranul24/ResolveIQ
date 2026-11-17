"""Evaluate and (re)train the ticket classifier:  python -m ml.train

Prints a held-out classification report, then fits on the full dataset and
saves ml/model.joblib (the API also trains on first start if the file is missing).
"""

from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from app.triage import MODEL_PATH, build_pipeline, load_dataset, train_and_save


def main() -> None:
    texts, labels = load_dataset()
    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )
    predictions = build_pipeline().fit(x_train, y_train).predict(x_test)

    print(f"Rows: {len(texts)}  |  train: {len(x_train)}  test: {len(x_test)}")
    print(f"Held-out accuracy: {accuracy_score(y_test, predictions):.3f}")
    print(classification_report(y_test, predictions, digits=3))
    print("Note: the data is synthetic (see ml/generate_data.py), so this score is an upper bound.")

    train_and_save()
    print(f"Saved model trained on all rows -> {MODEL_PATH}")


if __name__ == "__main__":
    main()
