package com.sijo.mcpboondmanager.service;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryData;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionarySetting;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryEntryDto;
import com.sijo.mcpboondmanager.exception.ExternalServiceException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.ParameterizedTypeReference;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AvailabilityDictionaryResolverTest {

    @Mock
    private BoondManagerClient client;

    @Test
    void givenKnownId_whenResolve_thenReturnsDictionaryLabel() {
        stubDictionary();
        AvailabilityDictionaryResolver resolver = new AvailabilityDictionaryResolver(client);

        assertThat(resolver.resolve("0")).isEqualTo("Immédiate");
        assertThat(resolver.resolve("3")).isEqualTo("3 mois");
        assertThat(resolver.resolve("5")).isEqualTo("Pas disponible");
    }

    @Test
    void givenDateValue_whenResolve_thenReturnsDateVerbatimWithoutHittingDictionary() {
        AvailabilityDictionaryResolver resolver = new AvailabilityDictionaryResolver(client);

        assertThat(resolver.resolve("2026-06-01")).isEqualTo("2026-06-01");
        // a date-based availability never needs the dictionary
        verifyNoInteractions(client);
    }

    @Test
    void givenSentinelNullOrUnknownId_whenResolve_thenReturnsNull() {
        stubDictionary();
        AvailabilityDictionaryResolver resolver = new AvailabilityDictionaryResolver(client);

        assertThat(resolver.resolve("-1")).isNull();
        assertThat(resolver.resolve(null)).isNull();
        assertThat(resolver.resolve("  ")).isNull();
        assertThat(resolver.resolve("999")).isNull();
    }

    @Test
    void givenMultipleResolves_whenResolve_thenDictionaryIsFetchedOnce() {
        stubDictionary();
        AvailabilityDictionaryResolver resolver = new AvailabilityDictionaryResolver(client);

        resolver.resolve("0");
        resolver.resolve("3");
        resolver.resolve("5");

        verify(client, times(1)).get(eq("/application/dictionary"),
                any(ParameterizedTypeReference.class));
    }

    @Test
    void givenDictionaryUnavailable_whenResolve_thenDegradesToNullAndRetries() {
        when(client.get(eq("/application/dictionary"), any(ParameterizedTypeReference.class)))
                .thenThrow(new ExternalServiceException("down", "/application/dictionary", null))
                .thenReturn(dictionaryEnvelope());
        AvailabilityDictionaryResolver resolver = new AvailabilityDictionaryResolver(client);

        // first call fails to load the dictionary -> graceful degradation (not cached)
        assertThat(resolver.resolve("3")).isNull();
        // second call succeeds because the failure was not cached
        assertThat(resolver.resolve("3")).isEqualTo("3 mois");
        verify(client, times(2)).get(eq("/application/dictionary"),
                any(ParameterizedTypeReference.class));
    }

    private void stubDictionary() {
        when(client.get(eq("/application/dictionary"), any(ParameterizedTypeReference.class)))
                .thenReturn(dictionaryEnvelope());
    }

    private static BoondDictionaryEnvelope dictionaryEnvelope() {
        List<DictionaryEntryDto> availability = List.of(
                new DictionaryEntryDto("0", "Immédiate"),
                new DictionaryEntryDto("1", "1 mois"),
                new DictionaryEntryDto("2", "De 1 à 3 mois"),
                new DictionaryEntryDto("3", "3 mois"),
                new DictionaryEntryDto("4", "> 3 mois"),
                new DictionaryEntryDto("5", "Pas disponible")
        );
        BoondDictionarySetting setting = new BoondDictionarySetting(
                null, null, availability, null, null, null, null, null, null, null, null, null, null);
        return new BoondDictionaryEnvelope(new BoondDictionaryData(setting));
    }
}