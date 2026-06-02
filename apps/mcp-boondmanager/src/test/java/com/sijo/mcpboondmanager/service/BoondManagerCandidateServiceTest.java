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
import com.sijo.mcpboondmanager.exception.ExternalServiceException;
import com.sijo.mcpboondmanager.support.TestFixtures;
import org.junit.jupiter.api.BeforeEach;
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
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class BoondManagerCandidateServiceTest {

    private static final ResolvedExperience RESOLVED_EXPERIENCE =
            new ResolvedExperience(3, false, true, "3 ans");

    @Mock
    private BoondManagerClient client;

    @Mock
    private ExperienceDictionaryResolver experienceResolver;

    @BeforeEach
    void stubExperienceResolver() {
        lenient().when(experienceResolver.resolve(any())).thenReturn(RESOLVED_EXPERIENCE);
    }

    @Test
    void givenDictionaryEndpoint_whenGetDictionary_thenMapsEnvelopeToMcpResponse() {
        BoondDictionaryEnvelope envelope = dictionaryEnvelope();
        when(client.get(eq("/application/dictionary"), any(Consumer.class),
                any(ParameterizedTypeReference.class)))
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
        when(client.get(eq("/application/dictionary"), any(Consumer.class),
                any(ParameterizedTypeReference.class)))
                .thenThrow(backend);

        assertThatThrownBy(() -> service().getDictionary())
                .isInstanceOfSatisfying(DictionaryResolutionException.class, ex -> {
                    assertThat(ex.status()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
                    assertThat(ex.path()).isEqualTo("/application/dictionary");
                    assertThat(ex.getCause()).isSameAs(backend);
                });
    }

    @Test
    void givenLanguage_whenGetDictionary_thenPassesLanguageQueryParam() {
        when(client.get(eq("/application/dictionary"), any(Consumer.class),
                any(ParameterizedTypeReference.class)))
                .thenReturn(dictionaryEnvelope());

        service().getDictionary("en");

        ArgumentCaptor<Consumer<UriBuilder>> queryCaptor = ArgumentCaptor.captor();
        verify(client).get(eq("/application/dictionary"), queryCaptor.capture(),
                any(ParameterizedTypeReference.class));
        UriComponentsBuilder builder = UriComponentsBuilder.newInstance();
        queryCaptor.getValue().accept(builder);
        assertThat(builder.build().getQueryParams()).containsEntry("language", List.of("en"));
    }

    @Test
    void givenBlankLanguage_whenGetDictionary_thenOmitsLanguageQueryParam() {
        when(client.get(eq("/application/dictionary"), any(Consumer.class),
                any(ParameterizedTypeReference.class)))
                .thenReturn(dictionaryEnvelope());

        service().getDictionary("  ");

        ArgumentCaptor<Consumer<UriBuilder>> queryCaptor = ArgumentCaptor.captor();
        verify(client).get(eq("/application/dictionary"), queryCaptor.capture(),
                any(ParameterizedTypeReference.class));
        UriComponentsBuilder builder = UriComponentsBuilder.newInstance();
        queryCaptor.getValue().accept(builder);
        assertThat(builder.build().getQueryParams()).doesNotContainKey("language");
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
        assertThat(response.candidates().getFirst().experience()).isEqualTo(3);
        assertThat(response.candidates().getFirst().experienceMinYears()).isEqualTo(3);
        assertThat(response.candidates().getFirst().experienceSpecified()).isTrue();
        assertThat(response.meta().totalRows()).isEqualTo(1);
        assertThat(response.meta().currentPage()).isEqualTo(1);

        ArgumentCaptor<Consumer<UriBuilder>> queryCaptor = ArgumentCaptor.captor();
        verify(client).get(eq("/candidates"), queryCaptor.capture(), any(ParameterizedTypeReference.class));

        UriComponentsBuilder builder = UriComponentsBuilder.newInstance();
        queryCaptor.getValue().accept(builder);
        assertThat(builder.build().getQueryParams())
                .containsEntry("keywords", List.of("java"))
                .containsEntry("keywordsType", List.of("resumeTd"))
                .containsEntry("candidateStates[]", List.of("2", "5"))
                .containsEntry("availabilityTypes[]", List.of("9"))
                .containsEntry("contractTypes[]", List.of("1"))
                .containsEntry("experiences[]", List.of("3"))
                .containsEntry("expertiseAreas[]", List.of("backend", "microservices"))
                .containsEntry("activityAreas[]", List.of("profilsdeveloppeur"))
                .containsEntry("mobilityAreas", List.of("idf"))
                .containsEntry("languages[]", List.of("anglais|courant"))
                .containsEntry("tools[]", List.of("JAVA"))
                .containsEntry("evaluations[]", List.of("4"))
                .containsEntry("sources[]", List.of("4"))
                .containsEntry("shields[]", List.of("complete"))
                .containsEntry("location", List.of("Paris"))
                .containsEntry("geoDistance", List.of("50"))
                .containsEntry("period", List.of("updated"))
                .containsEntry("startDate", List.of("2026-01-01"))
                .containsEntry("endDate", List.of("2026-06-01"))
                .containsEntry("page", List.of("1"))
                .containsEntry("maxResults", List.of("25"))
                .containsEntry("sort[]", List.of("updateDate"))
                .containsEntry("order", List.of("desc"))
                .containsEntry("columns[]",
                        List.of("name", "title", "state", "availability", "expertiseAreas", "experience"))
                .doesNotContainKeys("candidateTypes[]", "coordinates", "periodDynamic");
    }

    @Test
    void givenSearchRequestWithNullFilters_whenSearchCandidates_thenOmitsNullParams() {
        CandidateSearchRequestDto request = new CandidateSearchRequestDto(
                "java", null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null, 1, 25, null, null, null
        );
        when(client.get(eq("/candidates"), any(Consumer.class), any(ParameterizedTypeReference.class)))
                .thenReturn(searchEnvelope());

        service().searchCandidates(request);

        ArgumentCaptor<Consumer<UriBuilder>> queryCaptor = ArgumentCaptor.captor();
        verify(client).get(eq("/candidates"), queryCaptor.capture(), any(ParameterizedTypeReference.class));

        UriComponentsBuilder builder = UriComponentsBuilder.newInstance();
        queryCaptor.getValue().accept(builder);
        assertThat(builder.build().getQueryParams().keySet())
                .containsExactlyInAnyOrder("keywords", "page", "maxResults");
    }

    @Test
    void givenCandidateId_whenGetCandidateDetail_thenMapsEnvelopeToMcpDetail() {
        when(client.get(eq("/candidates/42/information"), any(ParameterizedTypeReference.class)))
                .thenReturn(detailEnvelope());

        CandidateDetailDto response = service().getCandidateDetail(42);

        assertThat(response.id()).isEqualTo(42);
        assertThat(response.firstName()).isEqualTo("Ada");
        assertThat(response.email()).isEqualTo("ada@example.test");
        assertThat(response.contractType()).isEqualTo(2);
        assertThat(response.city()).isEqualTo("Paris");
        assertThat(response.sourceType()).isEqualTo(1);
        assertThat(response.sourceDetail()).isEqualTo("LinkedIn");
    }

    @Test
    void givenCandidateId_whenGetCandidateTechnicalDocument_thenCallsTechnicalDataPath() {
        when(client.get(eq("/candidates/42/technical-data"), any(ParameterizedTypeReference.class)))
                .thenReturn(technicalDocumentEnvelope());

        TechnicalDocumentDto response = service().getCandidateTechnicalDocument(42);

        assertThat(response.id()).isEqualTo(42);
        assertThat(response.tdId()).isEqualTo("101");
        assertThat(response.skills()).isEqualTo("Java, Spring, PostgreSQL");
        assertThat(response.tools())
                .extracting(TechnicalDocumentDto.ToolProficiency::tool,
                        TechnicalDocumentDto.ToolProficiency::level)
                .containsExactly(org.assertj.core.groups.Tuple.tuple("IntelliJ", 5));
        assertThat(response.diplomas()).containsExactly("Engineering school");

        // raw experience id is preserved and the language-neutral fields come from the resolver
        assertThat(response.experience()).isEqualTo(3);
        assertThat(response.experienceMinYears()).isEqualTo(3);
        assertThat(response.experienceOpenEnded()).isFalse();
        assertThat(response.experienceSpecified()).isTrue();
        assertThat(response.experienceLabelRaw()).isEqualTo("3 ans");
        verify(experienceResolver).resolve(3);
    }

    @Test
    void givenTechnicalDataPathFails_whenGetCandidateTechnicalDocument_thenTriesPluralFallbackPath() {
        BoondApiException backend = new BoondApiException(
                "boom", HttpStatus.INTERNAL_SERVER_ERROR, "/candidates/42/technical-data", null);
        when(client.get(eq("/candidates/42/technical-data"), any(ParameterizedTypeReference.class)))
                .thenThrow(backend);
        when(client.get(eq("/candidates/42/technical-datas"), any(ParameterizedTypeReference.class)))
                .thenReturn(technicalDocumentEnvelope());

        TechnicalDocumentDto response = service().getCandidateTechnicalDocument(42);

        assertThat(response.id()).isEqualTo(42);
        assertThat(response.skills()).isEqualTo("Java, Spring, PostgreSQL");
        assertThat(response.tdId()).isEqualTo("101");
    }

    @Test
    void givenTechnicalDataReturnsListEnvelope_whenGetCandidateTechnicalDocument_thenMapsFirstRecord() {
        ExternalServiceException parseAsSingleFailure = new ExternalServiceException(
                "single envelope parse failed", "/candidates/42/technical-data", null);
        when(client.get(eq("/candidates/42/technical-data"), any(ParameterizedTypeReference.class)))
                .thenThrow(parseAsSingleFailure)
                .thenReturn(technicalDocumentListEnvelope());

        TechnicalDocumentDto response = service().getCandidateTechnicalDocument(42);

        assertThat(response.id()).isEqualTo(42);
        assertThat(response.skills()).isEqualTo("Java, Spring, PostgreSQL");
        assertThat(response.tdId()).isEqualTo("101");
    }

    @Test
    void givenCandidateNotFound_whenGetCandidateDetail_thenMapsToCandidateNotFoundException() {
        BoondApiException backend = new BoondApiException(
                "missing", HttpStatus.NOT_FOUND, "/candidates/404/information", null);
        when(client.get(eq("/candidates/404/information"), any(ParameterizedTypeReference.class)))
                .thenThrow(backend);

        assertThatThrownBy(() -> service().getCandidateDetail(404))
                .isInstanceOfSatisfying(CandidateNotFoundException.class, ex -> {
                    assertThat(ex.candidateId()).isEqualTo(404);
                    assertThat(ex.path()).isEqualTo("/candidates/404/information");
                    assertThat(ex.getCause()).isSameAs(backend);
                });
    }

    @Test
    void givenTechnicalDocumentNotFound_whenGetCandidateTechnicalDocument_thenMapsToCandidateNotFoundException() {
        BoondApiException backend = new BoondApiException(
                "missing", HttpStatus.NOT_FOUND, "/candidates/404/technical-data", null);
        BoondApiException fallbackBackend = new BoondApiException(
                "missing", HttpStatus.NOT_FOUND, "/candidates/404/technical-datas", null);
        when(client.get(eq("/candidates/404/technical-data"), any(ParameterizedTypeReference.class)))
                .thenThrow(backend);
        when(client.get(eq("/candidates/404/technical-datas"), any(ParameterizedTypeReference.class)))
                .thenThrow(fallbackBackend);

        assertThatThrownBy(() -> service().getCandidateTechnicalDocument(404))
                .isInstanceOfSatisfying(CandidateNotFoundException.class, ex ->
                        assertThat(ex.candidateId()).isEqualTo(404));
    }

    @Test
    void givenNon404BoondApiException_whenGetCandidateDetail_thenPropagatesOriginalException() {
        BoondApiException backend = new BoondApiException(
                "boom", HttpStatus.INTERNAL_SERVER_ERROR, "/candidates/42/information", null);
        when(client.get(eq("/candidates/42/information"), any(ParameterizedTypeReference.class)))
                .thenThrow(backend);

        assertThatThrownBy(() -> service().getCandidateDetail(42))
                .isSameAs(backend);
    }

    private BoondManagerCandidateService service() {
        return new BoondManagerCandidateService(client, experienceResolver);
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
                List.of(new DictionaryOptionEntryDto(
                        List.of(new DictionaryOptionEntryDto.OptionId("finance", "Finance")), "Sectors")),
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
                1, "9", 2,
                List.of("idf"), "Paris", "FR",
                "Senior Java Engineer", 3, "Java, Spring, React",
                List.of("Engineering school"), List.of("backend"), List.of("finance"),
                List.of(new BoondTechnicalDocumentAttributes.Tool("IntelliJ", 5)),
                List.of(new BoondTechnicalDocumentAttributes.Language("fr", "native")));
        return new BoondListEnvelope<>(
                List.of(new BoondData<>("42", "candidate", attrs)),
                new BoondMeta(new BoondMeta.Totals(1), 1));
    }

    private BoondSingleEnvelope<BoondCandidateDetailAttributes> detailEnvelope() {
        BoondCandidateDetailAttributes attrs = new BoondCandidateDetailAttributes(
                "Ada", "Lovelace", "ada@example.test", null, null,
                "+33100000000", null, null, null,
                1, "1990-01-01", "1 rue de test", "75001", "Paris", "FR", null,
                "STAGIAIRE", "A. L.", 1, 2, "9",
                List.of("idf"),
                new BoondCandidateDetailAttributes.Source(1, "LinkedIn"),
                "4", "Strong backend profile",
                "2025-01-01", "2026-02-01", "manual");
        return new BoondSingleEnvelope<>(new BoondData<>("42", "candidate", attrs));
    }

    private BoondSingleEnvelope<BoondTechnicalDocumentAttributes> technicalDocumentEnvelope() {
        BoondTechnicalDocumentAttributes attrs = new BoondTechnicalDocumentAttributes(
                "101", "Senior Java Engineer", "Detailed technical profile", "Backend engineer",
                3, "bac5",
                List.of("Engineering school"), "Java, Spring, PostgreSQL",
                List.of("backend"), List.of("finance"),
                List.of(new BoondTechnicalDocumentAttributes.Tool("IntelliJ", 5)),
                List.of(new BoondTechnicalDocumentAttributes.Language("en", "fluent")));
        return new BoondSingleEnvelope<>(new BoondData<>("42", "candidate", attrs));
    }

    private BoondListEnvelope<BoondTechnicalDocumentAttributes> technicalDocumentListEnvelope() {
        BoondTechnicalDocumentAttributes attrs = new BoondTechnicalDocumentAttributes(
                "101", "Senior Java Engineer", "Detailed technical profile", "Backend engineer",
                3, "bac5",
                List.of("Engineering school"), "Java, Spring, PostgreSQL",
                List.of("backend"), List.of("finance"),
                List.of(new BoondTechnicalDocumentAttributes.Tool("IntelliJ", 5)),
                List.of(new BoondTechnicalDocumentAttributes.Language("en", "fluent")));
        return new BoondListEnvelope<>(
                List.of(new BoondData<>("42", "candidate", attrs)),
                new BoondMeta(new BoondMeta.Totals(1), 1));
    }
}
