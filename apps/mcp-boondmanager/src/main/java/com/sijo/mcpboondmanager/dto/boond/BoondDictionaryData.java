package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * Body of the {@code /application/dictionary} response, found directly under {@code data}.
 * It only carries the {@code setting} business object — no JSON:API {@code id}/{@code type}.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondDictionaryData(
        BoondDictionarySetting setting
) {
}