# Architecture: AIOps for Payment Service Anomaly Detection

## End-to-End Data Layer
```mermaid
flowchart TD
    %% Service Layer
    subgraph Service
        PS[Payment Service\n(Java/Spring Boot)]
        OTEL_SDK[OpenTelemetry SDK]
        PS -- instrumented with --> OTEL_SDK
    end

    %% Collection Layer
    subgraph Collection
        OTEL_COL[OTel Collector\n(Sidecar/DaemonSet)]
        OTEL_SDK -- gRPC/HTTP --> OTEL_COL
    end

    %% Transport Layer
    subgraph Transport
        KAFKA[Apache Kafka\n(Event Bus)]
        OTEL_COL -- Push logs/metrics --> KAFKA
    end

    %% Processing Layer
    subgraph Processing
        FLINK[Apache Flink\n(Stream Processing)]
        KAFKA -- Consume stream --> FLINK
        FLINK -- Compute Rolling Features --> FLINK
        FLINK -- Detect Anomalies --> FLINK
    end

    %% Storage Layer
    subgraph Storage
        ES[(Elasticsearch\n/ OpenSearch)]
        FLINK -- Write features/alerts --> ES
    end

    %% Query / ML
    subgraph Query_ML
        GRAFANA[Grafana\n(Dashboards)]
        ML[ML Anomaly Service\n(Python/FastAPI)]
        ES -- Query data --> GRAFANA
        ES -- Read historical data --> ML
        ML -- Update models --> FLINK
    end
```

## Component Tool Choices
- **Service Instrumentation:** OpenTelemetry SDK (vendor-neutral, wide language support).
- **Collection:** OpenTelemetry Collector (batching, filtering, standardizing telemetry).
- **Transport:** Apache Kafka (highly scalable, decouples ingestion from processing).
- **Processing:** Apache Flink (true stream processing, stateful, windowing support out-of-the-box).
- **Storage:** Elasticsearch / OpenSearch (excellent text search for logs, good for time-series and fast querying).
- **Query/ML:** Grafana (rich visualization, native ES support). ML models can be retrained offline and deployed to Flink via broadcast state or side-services.
