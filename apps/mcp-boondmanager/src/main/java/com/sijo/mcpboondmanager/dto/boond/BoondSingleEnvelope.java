package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondSingleEnvelope<A>(
        BoondData<A> data
) {
}