package com.sijo.mcpboondmanager.config;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;
import org.springframework.util.unit.DataSize;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;

@Validated
@ConfigurationProperties(prefix = "boondmanager")
public record BoondManagerProperties(
        @NotBlank
        String baseUrl,
        @NotBlank
        String jwtClient,
        @NotNull
        Duration timeout,
        @NotNull
        @DefaultValue
        Webclient webclient
) {

    /**
     * Transport/codec tuning for the BoondManager WebClient.
     */
    public record Webclient(
            @NotNull
            @DefaultValue("16MB")
            DataSize maxInMemorySize
    ) {
    }
}