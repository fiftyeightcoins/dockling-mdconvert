# --- Build stage ---
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN mvn -q -DskipTests package

# --- Runtime stage ---
FROM eclipse-temurin:17-jre-jammy
WORKDIR /app

# Install Python + docling (Docling itself is a Python library/CLI)
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && pip3 install --no-cache-dir --break-system-packages docling \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app/target/docling-spring-1.0.0.jar app.jar

ENV DOCLING_EXECUTABLE=docling
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
