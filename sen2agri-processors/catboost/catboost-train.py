#!/usr/bin/env python3
import argparse

import geopandas as gpd
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.model_selection import train_test_split


def read_file(path):
    if path.endswith(".parquet"):
        return gpd.read_parquet(path)
    if path.endswith(".arrow"):
        return gpd.read_feather(path)
    return gpd.read_file(path)


parser = argparse.ArgumentParser(description="Train a CatBoost classifier.")
parser.add_argument(
    "--inputs",
    nargs="+",
    type=str,
    help="Paths to the samples files",
)
parser.add_argument("--model", type=str, help="Name for the output model file")
parser.add_argument(
    "--feature-columns", nargs="+", required=True, help="List of feature column names"
)
parser.add_argument(
    "--label-column", type=str, required=True, help="Name of the label column"
)
parser.add_argument(
    "--iterations", type=int, default=1000, help="Maximum number of trees"
)
parser.add_argument("--depth", type=int, default=7, help="Depth of the trees")
parser.add_argument(
    "--early-stopping-rounds", type=int, default=20, help="Early stopping rounds"
)
parser.add_argument(
    "--test-split", type=float, default=0.1, help="Test split for early stopping"
)
parser.add_argument(
    "--random-state", type=int, default=42, help="Random state for test split"
)

args = parser.parse_args()

df = pd.concat((read_file(file) for file in args.inputs))

features = df[args.feature_columns]
labels = df[args.label_column]
del df

features_train, features_eval, labels_train, labels_eval = train_test_split(
    features, labels, test_size=args.test_split, random_state=args.random_state
)
model = CatBoostClassifier(
    iterations=args.iterations,
    loss_function="MultiClass",
    depth=args.depth,
    verbose=True,
)
model.fit(
    features_train,
    labels_train,
    eval_set=(features_eval, labels_eval),
    early_stopping_rounds=args.early_stopping_rounds,
    use_best_model=True,
)
model.save_model(args.model)
