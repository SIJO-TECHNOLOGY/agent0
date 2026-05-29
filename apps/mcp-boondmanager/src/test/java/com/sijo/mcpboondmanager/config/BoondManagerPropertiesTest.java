package com.sijo.mcpboondmanager.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Configuration;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

class BoondManagerPropertiesTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(PropertiesConfiguration.class);

    @Test
    void givenAllProperties_whenContextStarts_thenBindsBaseUrlAndJwt() {
        contextRunner
                .withPropertyValues(
                        "boondmanager.base-url=https://ui.boondmanager.com/api",
                        "boondmanager.jwt-client=eyTestJwt",
                        "boondmanager.timeout=3s"
                )
                .run(context -> {
                    assertThat(context).hasSingleBean(BoondManagerProperties.class);
                    BoondManagerProperties properties = context.getBean(BoondManagerProperties.class);
                    assertThat(properties.baseUrl()).isEqualTo("https://ui.boondmanager.com/api");
                    assertThat(properties.jwtClient()).isEqualTo("eyTestJwt");
                });
    }

    @Test
    void givenTimeoutProperty_whenContextStarts_thenBindsDuration() {
        contextRunner
                .withPropertyValues(
                        "boondmanager.base-url=https://ui.boondmanager.com/api",
                        "boondmanager.jwt-client=eyTestJwt",
                        "boondmanager.timeout=1500ms"
                )
                .run(context -> assertThat(context.getBean(BoondManagerProperties.class).timeout())
                        .isEqualTo(Duration.ofMillis(1_500)));
    }

    @Test
    void givenMissingBaseUrl_whenContextStarts_thenFailsConfigurationBinding() {
        contextRunner
                .withPropertyValues(
                        "boondmanager.jwt-client=eyTestJwt",
                        "boondmanager.timeout=3s"
                )
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure()).hasStackTraceContaining("baseUrl");
                });
    }

    @Test
    void givenMissingJwtClient_whenContextStarts_thenFailsConfigurationBinding() {
        contextRunner
                .withPropertyValues(
                        "boondmanager.base-url=https://ui.boondmanager.com/api",
                        "boondmanager.timeout=3s"
                )
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure()).hasStackTraceContaining("jwtClient");
                });
    }

    @Configuration(proxyBeanMethods = false)
    @EnableConfigurationProperties(BoondManagerProperties.class)
    static class PropertiesConfiguration {
    }
}