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
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ExperienceDictionaryResolverTest {

    @Mock
    private BoondManagerClient client;

    @Test
    void givenKnownId_whenResolve_thenParsesDictionaryLabel() {
        stubDictionary();
        ExperienceDictionaryResolver resolver = new ExperienceDictionaryResolver(client);

        assertThat(resolver.resolve(3))
                .isEqualTo(new ResolvedExperience(3, false, true, "3 ans"));
        // ids are non-sequential: id 11 maps to "4 ans"
        assertThat(resolver.resolve(11))
                .isEqualTo(new ResolvedExperience(4, false, true, "4 ans"));
        assertThat(resolver.resolve(10))
                .isEqualTo(new ResolvedExperience(10, true, true, "> à 10 ans"));
        assertThat(resolver.resolve(0))
                .isEqualTo(new ResolvedExperience(0, false, true, "Pas d'expérience"));
    }

    @Test
    void givenSentinelNullOrUnknownId_whenResolve_thenUnspecified() {
        stubDictionary();
        ExperienceDictionaryResolver resolver = new ExperienceDictionaryResolver(client);

        assertThat(resolver.resolve(-1)).isEqualTo(ResolvedExperience.UNSPECIFIED);
        assertThat(resolver.resolve(null)).isEqualTo(ResolvedExperience.UNSPECIFIED);
        assertThat(resolver.resolve(999)).isEqualTo(ResolvedExperience.UNSPECIFIED);
    }

    @Test
    void givenMultipleResolves_whenResolve_thenDictionaryIsFetchedOnce() {
        stubDictionary();
        ExperienceDictionaryResolver resolver = new ExperienceDictionaryResolver(client);

        resolver.resolve(3);
        resolver.resolve(10);
        resolver.resolve(11);

        verify(client, times(1)).get(eq("/application/dictionary"),
                any(ParameterizedTypeReference.class));
    }

    @Test
    void givenDictionaryUnavailable_whenResolve_thenDegradesToUnspecifiedAndRetries() {
        when(client.get(eq("/application/dictionary"), any(ParameterizedTypeReference.class)))
                .thenThrow(new ExternalServiceException("down", "/application/dictionary", null))
                .thenReturn(dictionaryEnvelope());
        ExperienceDictionaryResolver resolver = new ExperienceDictionaryResolver(client);

        // first call fails to load the dictionary -> graceful degradation (not cached)
        assertThat(resolver.resolve(3)).isEqualTo(ResolvedExperience.UNSPECIFIED);
        // second call succeeds because the failure was not cached
        assertThat(resolver.resolve(3))
                .isEqualTo(new ResolvedExperience(3, false, true, "3 ans"));
        verify(client, times(2)).get(eq("/application/dictionary"),
                any(ParameterizedTypeReference.class));
    }

    private void stubDictionary() {
        when(client.get(eq("/application/dictionary"), any(ParameterizedTypeReference.class)))
                .thenReturn(dictionaryEnvelope());
    }

    private static BoondDictionaryEnvelope dictionaryEnvelope() {
        List<DictionaryEntryDto> experience = List.of(
                new DictionaryEntryDto("0", "Pas d'expérience"),
                new DictionaryEntryDto("3", "3 ans"),
                new DictionaryEntryDto("11", "4 ans"),
                new DictionaryEntryDto("10", "> à 10 ans")
        );
        BoondDictionarySetting setting = new BoondDictionarySetting(
                null, null, null, null, experience, null, null, null, null, null, null, null, null);
        return new BoondDictionaryEnvelope(new BoondDictionaryData(setting));
    }
}
