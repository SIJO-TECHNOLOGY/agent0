package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondMeta(
        Totals totals,
        Integer currentPage
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Totals(Integer rows) {
    }
}