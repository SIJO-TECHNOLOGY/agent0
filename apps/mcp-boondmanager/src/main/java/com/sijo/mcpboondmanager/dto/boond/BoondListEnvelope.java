package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondListEnvelope<A>(
        List<BoondData<A>> data,
        BoondMeta meta
) {
}