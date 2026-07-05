# ML Engine Component Diagram

**C4 Level:** 3. Components

**Container in focus:** ML Engine

## Purpose

This diagram decomposes the ML Engine into its internal components and illustrates how machine learning capabilities are organised within Tiber. It identifies the responsibilities of each component, the separation between the online inference and offline training pipelines, and the interactions between shared infrastructure such as feature engineering, model management, prediction logging, and model storage.
The diagram demonstrates how the ML Engine separates prediction serving from model training while sharing common components to ensure training-serving consistency and a well-defined model lifecycle.

## Diagram

![ML Engine](../diagrams/ml-engine.svg)

## Key Decisions

- **Online inference and offline training are separated into independent pipelines:** The ML Engine is divided into two pipelines with distinct operational characteristics. The Online Inference Pipeline serves low-latency predictions to the API Service synchronously during notification intake, and to the Worker Service only for fallback or revalidation. The Offline Training Pipeline prepares datasets, trains models, and publishes new versions asynchronously and independently of live traffic. Separating these concerns means inference latency is never affected by a training run, training datasets can grow and be reprocessed without touching inference code, and each pipeline can be monitored, debugged, and evolved independently.

- **Feature engineering is shared between both pipelines via the Feature Builder:** Feature engineering logic, namely, encoding channel history, normalising timestamps to user timezone, computing content-length signals, encoding notification type, is centralised in a single Feature Builder component used by both the Inference API at serving time and the Dataset Builder at training time. This is the primary defence against training-serving skew: the condition where a model is trained on features shaped one way and served predictions on features shaped a different way, producing silently degraded accuracy. With a shared Feature Builder, any change to feature engineering applies to both pipelines simultaneously. A duplicate implementation in training and inference is not just redundant, it is a latent bug.

- **One predictor per prediction task:** Priority classification, send-time prediction, and channel preference prediction are implemented as three independent scikit-learn components rather than a single multi-output model. The alternative, which is a single model predicting all three outputs simultaneously, would couple their training data requirements, evaluation cycles, and model promotion decisions into one artifact. In practice this means: if send-time prediction accuracy degrades and requires retraining on new engagement data, only the Send-Time Predictor is retrained and promoted. The Priority Classifier and Channel Preference Predictor are unaffected. Independent models can be versioned, evaluated, and replaced independently. A multi-output model ties all three to the same training run and the same promotion decision.

- **The Model Registry is the boundary between training and inference:** The Model Registry acts as the explicit contract between the offline training and online inference pipelines. The Model Trainer publishes approved model versions to the registry after passing evaluation thresholds; inference components load models exclusively through the registry. This means models can be updated, rolled back, or promoted without changing any inference code. The registry also caches loaded model artifacts in memory, meaning disk or network reads occur only on version changes rather than on every inference request.

- **Model promotion is a deliberate step, not an automatic one:** The Model Trainer evaluates candidate models against a baseline and a minimum performance floor before publishing. A model that passes evaluation is written to object storage and its version registered in the Model Registry. It does not become the active serving model until it is explicitly promoted. This prevents a regression in training data quality or a poorly configured training run from silently replacing a production model. The promotion step is a checkpoint, not a formality.

- **Training begins with synthetic data and transitions without pipeline changes:** Tiber initially has no historical engagement data. The Training Data Source generates synthetic engagement data (realistic user personas with configurable engagement patterns and noise) during early development and model bootstrapping. As the platform accumulates real user interactions through the Engagement Tracker, the Training Data Source transitions to supplying historical engagement data. This transition requires no changes to the Dataset Builder, Model Trainer, or any other training pipeline component. The Training Data Source is the single point of change, and the `is_synthetic` flag on every training record ensures real and synthetic data are never silently mixed in the same training run.

- **Model artefacts are stored externally in object storage:** Trained models and training datasets are stored in S3-compatible object storage (S3 or MinIO for local development). The Model Registry retrieves published artefacts from storage at startup or on version change rather than holding them in application memory permanently. This means model artefacts persist independently of the running ML Engine process, survive restarts and redeployments without data loss, and can be inspected, downloaded, or rolled back directly from storage without touching the application.

- **The online inference pipeline is stateless:** The inference pipeline does not read from PostgreSQL or any other application database. All information required for a prediction, such as notification content, channel, recipient context, and project metadata, is supplied by the calling service as part of the inference request. This keeps each inference call self-contained, makes the inference pipeline independently testable without a database, and means the inference pipeline can scale horizontally without introducing distributed state management.

- **Predictions and training runs are both observable:** Every inference call is recorded by the Prediction Logger with model version, prediction result, confidence score, and latency, then exported to the observability platform via OTLP. Every training run exports evaluation metrics, namely precision, recall, F1 per class for classifiers, MAE for the send-time predictor, through the same observability path. This gives end-to-end visibility into both model serving quality and model development health, and provides the data needed to detect model drift over time.

## What This Diagram Does Not Show

This diagram does not show the internal feature engineering logic within the Feature Builder — the specific features computed, their encoding strategies, and the decisions about which signals are included or excluded. The scikit-learn model configurations, hyperparameter choices, and training methodology for each predictor are not shown here. The RabbitMQ exchange and queue topology for delivering engagement events to the Engagement Tracker is covered in the messaging topology document.
