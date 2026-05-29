package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryEntryDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryOptionEntryDto;

import java.util.List;

/**
 * The {@code setting} business object returned under {@code data.setting} by
 * {@code /application/dictionary}. Each reference list is deserialized into the reusable
 * {@link DictionaryEntryDto} ({@code id} + {@code label}), except {@code mobilityArea} whose
 * entries expose a list of sub-options under an {@code option} array ({@link DictionaryOptionEntryDto}).
 *
 * <p>{@code state} and {@code typeOf} are nested objects (e.g. {@code state.candidate},
 * {@code typeOf.contract}) rather than flat arrays, so they get dedicated nested records.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondDictionarySetting(
        State state,
        TypeOf typeOf,
        List<DictionaryEntryDto> availability,
        List<DictionaryOptionEntryDto> mobilityArea,
        List<DictionaryEntryDto> experience,
        List<DictionaryEntryDto> training,
        List<DictionaryEntryDto> expertiseArea,
        List<DictionaryEntryDto> activityArea,
        List<DictionaryEntryDto> tool,
        List<DictionaryEntryDto> languageSpoken,
        List<DictionaryEntryDto> languageLevel,
        List<DictionaryEntryDto> evaluation,
        List<DictionaryEntryDto> source
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record State(List<DictionaryEntryDto> candidate) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record TypeOf(List<DictionaryEntryDto> contract) {
    }
}