# ML Engine Component Diagram

**C4 Level:** 3. Components

**Container in focus:** ML Engine

## Purpose

This diagram decomposes the ML Engine into its internal components and illustrates how online machine learning inference is organised within Tiber. It identifies the responsibilities of each component, the flow of inference requests through the prediction pipeline, and the interactions between shared infrastructure such as feature engineering, model management, and prediction logging.
The diagram demonstrates how the ML Engine separates request orchestration, feature construction, model execution, and observability into cohesive components while remaining stateless and independent of the notification domain.

## Diagram

![ml engine](..diagrams/ml-engine.svg)

## Key decisions

- **Online inference only:** The ML Engine performs inference exclusively. Model training, feature experimentation, evaluation, and retraining are intentionally excluded from this service and belong to an offline machine learning pipeline.
  This separation keeps inference lightweight, predictable, and independently deployable.

- **Feature engineering is centralized:** All feature construction is performed by the Feature Builder before reaching any prediction model. Individual predictors consume standardized feature vectors rather than implementing their own feature engineering logic. This prevents duplication and ensures consistency across all prediction tasks.

**One predictor per business capability:** Each prediction task is implemented as an independent component. Priority Classifier predicts notification priority, Send-Time Predictor recommends an optimal delivery time, and Channel Preference Predictor recommends the recipient's preferred delivery channel.
Each component owns exactly one prediction responsibility and can evolve independently without affecting the others.

**Models are managed through a registry:** Prediction models are never loaded directly by predictor components. Instead, the Model Registry owns model loading, caching, versioning, and lifecycle management. This provides a single abstraction for model access and enables future integration with external model registries without changing predictor implementations.

**The engine is stateless:** The ML Engine does not access PostgreSQL or other application databases. All information required for inference is supplied by the Worker Service as part of the inference request. This keeps the engine horizontally scalable and minimizes coupling with the rest of the platform.

**Every prediction is observable:** Each inference is recorded by the Prediction Logger, including: prediction result, confidence score, model version, inference latency, timestamp. These records support operational monitoring, model comparison, offline evaluation, and future model improvement without affecting the inference path.

## What this diagram does not show

This component diagram intentionally excludes several aspects of the machine learning lifecycle.

Specifically, it does not describe:

- offline model training
- dataset generation and feature extraction pipelines
- model evaluation and benchmarking
- model retraining workflows
- experiment tracking
- feature stores
- model deployment pipelines
- hyperparameter tuning
- A/B testing of models

These concerns belong to the offline ML platform and are intentionally separated from the online inference architecture represented here.
