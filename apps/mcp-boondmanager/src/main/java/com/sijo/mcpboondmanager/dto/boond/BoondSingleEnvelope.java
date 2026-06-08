package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondSingleEnvelope<A>(
        BoondData<A> data,
        List<BoondIncluded> included
) {
}