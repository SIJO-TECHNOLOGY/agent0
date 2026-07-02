# Sijo MCP BoondManager — Spring Boot MCP server
FROM maven:3.9-eclipse-temurin-21 AS builder

WORKDIR /build

COPY pom.xml ./
RUN mvn -B dependency:go-offline -q || true

COPY src ./src
RUN mvn -B package -DskipTests -q

FROM eclipse-temurin:21-jre

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app app

COPY --from=builder /build/target/*.jar app.jar

USER app

EXPOSE 8080

ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "-jar", "app.jar"]
