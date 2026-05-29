package com.sijo.mcpboondmanager.service;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateDetailAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateSummaryAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondData;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryData;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionarySetting;
import com.sijo.mcpboondmanager.dto.boond.BoondListEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondMeta;
import com.sijo.mcpboondmanager.dto.boond.BoondSingleEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondTechnicalDocumentAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondTechnicalDocumentSummaryAttributes;
import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryEntryDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryOptionEntryDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
import com.sijo.mcpboondmanager.exception.BoondApiException;
import com.sijo.mcpboondmanager.exception.CandidateNotFoundException;
import com.sijo.mcpboondmanager.exception.DictionaryResolutionException;
import com.sijo.mcpboondmanager.support.TestFixtures;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.web.util.UriBuilder;
import org.springframework.web.util.UriComponentsBuilder;

import java.util.List;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class BoondManagerCandidateServiceTest {

    @Mock
    private BoondManagerClient client;

    @Test
    void givenDictionaryEndpoint_whenGetDictionary_thenMapsEnvelopeToMcpResponse() {
        BoondDictionaryEnvelope envelope = dictionaryEnvelope();
        when(client.get(eq("/application/dictionary"), any(ParameterizedTypeReference.class)))
                .thenReturn(envelope);

        DictionaryResponseDto response = service().getDictionary();

        assertThat(response.setting().state().candidate())
                .extracting(DictionaryEntryDto::id, DictionaryEntryDto::label)
                .containsExactly(org.assertj.core.groups.Tuple.tuple("1", "Active"));
        assertThat(response.setting().typeOf().contract())
                .extracting(DictionaryEntryDto::id)
                .containsExactly("2");
        assertThat(response.setting().mobilityArea())
                .extracting(entry -> entry.option().getFirst().id())
                .containsExactly("idf");
    }

    @Test
    void givenBoondApiFailure_whenGetDictionary_thenMapsToDictionaryResolutionException() {
        BoondApiException backend = new BoondApiException(
                "boom", HttpStatus.SERVICE_UNAVAILABLE, "/application/dictionary", null);
        when(client.get(eq("/application/dictionary"), any(ParameterizedTypeReference.class)))
                .thenThrow(backend);

        assertThatThrownBy(() -> service().getDictionary())
                .isInstanceOfSatisfying(DictionaryResolutionException.class, ex -> {
                    assertThat(ex.status()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
                    assertThat(ex.path()).isEqualTo("/application/dictionary");
                    assertThat(ex.getCause()).isSameAs(backend);
                });
    }

    @Test
    void givenCandidateSearchRequest_whenSearchCandidates_thenDelegatesWithAllQueryParameters() {
        CandidateSearchRequestDto request = TestFixtures.searchRequest();
        when(client.get(eq("/candidates"), any(Consumer.class), any(ParameterizedTypeReference.class)))
                .thenReturn(searchEnvelope());

        CandidateSearchResponseDto response = service().searchCandidates(request);

        assertThat(response.candidates()).hasSize(1);
        assertThat(response.candidates().getFirst().id()).isEqualTo(42);
        assertThat(response.candidates().getFirst().firstName()).isEqualTo("Ada");
        assertThat(response.meta().totalRows()).isEqualTo(1);
        assertThat(response.meta().currentPage()).isEqualTo(1);

        ArgumentCaptor<Consumer<UriBuilder>> queryCaptor = ArgumentCaptor.captor();
        verify(client).get(eq("/candidates"), queryCaptor.capture(), any(ParameterizedTypeReference.class));

        UriComponentsBuilder builder = UriComponentsBuilder.newInstance();
        queryCaptor.getValue().accept(builder);
        assertThat(builder.build().getQueryParams())
                .containsEntry("keywords", List.of("java"))
                .containsEntry("state", List.of("1"))
                .containsEntry("availabilityType", List.of("9"))
                .containsEntry("availabilityDate", List.of("2026-06-01"))
                .containsEntry("contractType", List.of("2"))
                .containsEntry("experience", List.of("3"))
                .containsEntry("training", List.of("bac5"))
                .containsEntry("expertiseAreas", List.of("backend|microservices"))
                .containsEntry("activityAreas", List.of("finance|industry"))
                .containsEntry("mobilityArea", List.of("idf"))
                .containsEntry("minSalary", List.of("40000.0"))
                .containsEntry("maxSalary", List.of("60000.0"))
                .containsEntry("minTjm", List.of("500.0"))
                .containsEntry("maxTjm", List.of("700.0"))
                .containsEntry("page", List.of("1"))
                .containsEntry("numberPerPage", List.of("25"));
    }

    @Test
    void givenSearchRequestWithNullFilters_whenSearchCandidates_thenOmitsNullParams() {
        CandidateSearchRequestDto request = new CandidateSearchRequestDto(
                "java", null, null, null, null, null, null, null,
                null, null, null, null, null, null, 1, 25
        );
        when(client.get(eq("/candidates"), any(Consumer.class), any(ParameterizedTypeReference.class)))
                .thenReturn(searchEnvelope());

        service().searchCandidates(request);

        ArgumentCaptor<Consumer<UriBuilder>> queryCaptor = ArgumentCaptor.captor();
        verify(client).get(eq("/candidates"), queryCaptor.capture(), any(ParameterizedTypeReference.class));

        UriComponentsBuilder builder = UriComponentsBuilder.newInstance();
        queryCaptor.getValue().accept(builder);
        assertThat(builder.build().getQueryParams().keySet())
                .containsExactlyInAnyOrder("keywords", "page", "numberPerPage");
    }

    @Test
    void givenCandidateId_whenGetCandidateDetail_thenMapsEnvelopeToMcpDetail() {
        when(client.get(eq("/candidates/42"), any(ParameterizedTypeReference.class)))
                .thenReturn(detailEnvelope());

        CandidateDetailDto response = service().getCandidateDetail(42);

        assertThat(response.id()).isEqualTo(42);
        assertThat(response.firstName()).isEqualTo("Ada");
        assertThat(response.email()).isEqualTo("ada@example.test");
        assertThat(response.technicalDocumentId()).isEqualTo(101);
    }

    @Test
    void givenCandidateId_whenGetCandidateTechnicalDocument_thenCallsTechnicalDataPath() {
        when(client.get(eq("/candidates/42/technical-data"), any(ParameterizedTypeReference.class)))
                .thenReturn(technicalDocumentEnvelope());

        TechnicalDocumentDto response = service().getCandidateTechnicalDocument(42);

        assertThat(response.id()).isEqualTo(101);
        assertThat(response.skills()).isEqualTo("Java, Spring, PostgreSQL");
        assertThat(response.candidateId()).isEqualTo(42);
    }

    @Test
    void givenCandidateNotFound_whenGetCandidateDetail_thenMapsToCandidateNotFoundException() {
        BoondApiException backend = new BoondApiException(
                "missing", HttpStatus.NOT_FOUND, "/candidates/404", null);
        when(client.get(eq("/candidates/404"), any(ParameterizedTypeReference.class)))
                .thenThrow(backend);

        assertThatThrownBy(() -> service().getCandidateDetail(404))
                .isInstanceOfSatisfying(CandidateNotFoundException.class, ex -> {
                    assertThat(ex.candidateId()).isEqualTo(404);
                    assertThat(ex.path()).isEqualTo("/candidates/404");
                    assertThat(ex.getCause()).isSameAs(backend);
                });
    }

    @Test
    void givenTechnicalDocumentNotFound_whenGetCandidateTechnicalDocument_thenMapsToCandidateNotFoundException() {
        BoondApiException backend = new BoondApiException(
                "missing", HttpStatus.NOT_FOUND, "/candidates/404/technical-data", null);
        when(client.get(eq("/candidates/404/technical-data"), any(ParameterizedTypeReference.class)))
                .thenThrow(backend);

        assertThatThrownBy(() -> service().getCandidateTechnicalDocument(404))
                .isInstanceOfSatisfying(CandidateNotFoundException.class, ex ->
                        assertThat(ex.candidateId()).isEqualTo(404));
    }

    @Test
    void givenNon404BoondApiException_whenGetCandidateDetail_thenPropagatesOriginalException() {
        BoondApiException backend = new BoondApiException(
                "boom", HttpStatus.INTERNAL_SERVER_ERROR, "/candidates/42", null);
        when(client.get(eq("/candidates/42"), any(ParameterizedTypeReference.class)))
                .thenThrow(backend);

        assertThatThrownBy(() -> service().getCandidateDetail(42))
                .isSameAs(backend);
    }

    private BoondManagerCandidateService service() {
        return new BoondManagerCandidateService(client);
    }

    private BoondDictionaryEnvelope dictionaryEnvelope() {
        BoondDictionarySetting setting = new BoondDictionarySetting(
                new BoondDictionarySetting.State(List.of(new DictionaryEntryDto("1", "Active"))),
                new BoondDictionarySetting.TypeOf(List.of(new DictionaryEntryDto("2", "CDI"))),
                List.of(new DictionaryEntryDto("9", "Available after date")),
                List.of(new DictionaryOptionEntryDto(
                        List.of(new DictionaryOptionEntryDto.OptionId("idf", "Ile-de-France")), "Ile-de-France")),
                List.of(new DictionaryEntryDto("3", "Senior")),
                List.of(new DictionaryEntryDto("bac5", "Bac+5")),
                List.of(new DictionaryEntryDto("backend", "Backend")),
                List.of(new DictionaryEntryDto("finance", "Finance")),
                List.of(new DictionaryEntryDto("java", "Java")),
                List.of(new DictionaryEntryDto("fr", "French")),
                List.of(new DictionaryEntryDto("5", "Native")),
                List.of(new DictionaryEntryDto("4", "Excellent")),
                List.of(new DictionaryEntryDto("1", "LinkedIn"))
        );
        return new BoondDictionaryEnvelope(new BoondDictionaryData(setting));
    }

    private BoondListEnvelope<BoondCandidateSummaryAttributes> searchEnvelope() {
        BoondCandidateSummaryAttributes attrs = new BoondCandidateSummaryAttributes(
                "Ada", "Lovelace", "ada@example.test",
                1, 9, "2026-06-01", 2,
                "idf", "Paris", "FR",
                40_000.0, 60_000.0, 500.0, 700.0,
                new BoondTechnicalDocumentSummaryAttributes(
                        "Senior Java Engineer", 3, "bac5", "Engineering school",
                        "Java, Spring, React", "backend", "finance",
                        "IntelliJ:5", "fr:5|en:4"));
        return new BoondListEnvelope<>(
                List.of(new BoondData<>("42", "candidate", attrs)),
                new BoondMeta(new BoondMeta.Totals(1), 1));
    }

    private BoondSingleEnvelope<BoondCandidateDetailAttributes> detailEnvelope() {
        BoondCandidateDetailAttributes attrs = new BoondCandidateDetailAttributes(
                "Ada", "Lovelace", "ada@example.test", null, null,
                "+33100000000", null, null, 1, "1990-01-01", "FR",
                "1 rue de test", "75001", "Paris", "FR",
                1, 4, 9, "2026-06-01", 2, "idf",
                55_000.0, 60_000.0, 70_000.0,
                600.0, 650.0, 750.0,
                1, "LinkedIn", "Strong backend profile",
                "2025-01-01", "2026-01-01", "2026-02-01",
                101, 7, 8);
        return new BoondSingleEnvelope<>(new BoondData<>("42", "candidate", attrs));
    }

    private BoondSingleEnvelope<BoondTechnicalDocumentAttributes> technicalDocumentEnvelope() {
        BoondTechnicalDocumentAttributes attrs = new BoondTechnicalDocumentAttributes(
                "Senior Java Engineer", "Detailed technical profile", "Backend engineer",
                3, "bac5", "Engineering school",
                "Java, Spring, PostgreSQL", "backend", "finance",
                "IntelliJ:5", "fr:5|en:4",
                Boolean.FALSE, "2025-01-01", "2026-01-01", 42);
        return new BoondSingleEnvelope<>(new BoondData<>("101", "technicaldata", attrs));
    }
}