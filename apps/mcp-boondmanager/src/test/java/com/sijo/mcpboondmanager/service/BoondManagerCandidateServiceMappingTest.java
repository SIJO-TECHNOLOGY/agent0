package com.sijo.mcpboondmanager.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateDetailAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateSummaryAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondListEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondSingleEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondTechnicalDocumentAttributes;
import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSummaryDto;
import com.sijo.mcpboondmanager.dto.candidate.ExperienceReference;
import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.stubbing.Answer;
import org.springframework.core.ParameterizedTypeReference;

import java.io.IOException;
import java.io.InputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Maps the real BoondManager fixture responses (saved verbatim from the live API under
 * {@code src/test/resources/fixtures/}) through {@link BoondManagerCandidateService} and asserts that the
 * fields newly exposed by the "transparent DTO" refactor are populated — no live API call is made: the
 * {@link BoondManagerClient} is stubbed to return the deserialized fixtures, switching on the request path.
 */
class BoondManagerCandidateServiceMappingTest {

    private final ObjectMapper mapper = new ObjectMapper();

    private BoondManagerClient client;
    private BoondManagerCandidateService service;

    private BoondDictionaryEnvelope dictionaryEnvelope;
    private BoondListEnvelope<BoondCandidateSummaryAttributes> searchEnvelope;
    private BoondSingleEnvelope<BoondCandidateDetailAttributes> detailEnvelope;
    private BoondSingleEnvelope<BoondTechnicalDocumentAttributes> technicalDocumentEnvelope;

    @BeforeEach
    void setUp() throws IOException {
        dictionaryEnvelope = readFixture("boond_dictionary.json", new TypeReference<>() {});
        searchEnvelope = readFixture("boond_search.json", new TypeReference<>() {});
        detailEnvelope = readFixture("boond_candidate_detail.json", new TypeReference<>() {});
        technicalDocumentEnvelope = readFixture("boond_technical_data.json", new TypeReference<>() {});

        client = mock(BoondManagerClient.class);
        Answer<Object> byPath = invocation -> fixtureForPath(invocation.getArgument(0));
        // Two-arg overload: get(path, type) — used for detail, technical-data and the resolvers' dictionary.
        when(client.get(anyString(), any(ParameterizedTypeReference.class))).thenAnswer(byPath);
        // Three-arg overload: get(path, uriCustomizer, type) — used for search and getDictionary.
        when(client.get(anyString(), any(), any(ParameterizedTypeReference.class))).thenAnswer(byPath);

        service = new BoondManagerCandidateService(
                client,
                new ExperienceDictionaryResolver(client),
                new AvailabilityDictionaryResolver(client));
    }

    @Test
    void searchCandidates_exposesScoringSignalsReferencesAndRelationships() {
        CandidateSearchResponseDto response = service.searchCandidates(emptyRequest());

        assertThat(response.candidates()).hasSize(2);
        CandidateSummaryDto candidate = response.candidates().get(0);

        // Identity / contact
        assertThat(candidate.id()).isEqualTo(42130);
        assertThat(candidate.email()).isEqualTo("woshicecile@gmail.com");
        assertThat(candidate.civility()).isEqualTo(1);

        // Rule 3 — implicit scoring signals
        assertThat(candidate.numberOfActivePositionings()).isZero();
        assertThat(candidate.numberOfResumes()).isEqualTo(1);
        assertThat(candidate.globalEvaluation()).isEqualTo("-1");
        assertThat(candidate.creationDate()).startsWith("2026-05-28");
        assertThat(candidate.updateDate()).startsWith("2026-06-08");
        // lastActionDate is column-gated and not requested in this fixture
        assertThat(candidate.lastActionDate()).isNull();

        // Rule 2 — both resolved label and raw availability are kept (raw "-1" resolves to null label)
        assertThat(candidate.availabilityRaw()).isEqualTo("-1");
        assertThat(candidate.availability()).isNull();

        // Source (id + detail)
        assertThat(candidate.sourceType()).isEqualTo(-1);
        assertThat(candidate.sourceDetail()).isEqualTo("Collective");

        // Rule 5 — nested work history preserved, not flattened
        assertThat(candidate.references()).hasSize(5);
        ExperienceReference firstReference = candidate.references().get(0);
        assertThat(firstReference.company()).isEqualTo("Orchestra");
        assertThat(firstReference.title()).contains("Stagiaire");
        assertThat(firstReference.startYear()).isEqualTo("2017");
        assertThat(firstReference.skills()).isNotBlank();
        assertThat(firstReference.description()).isNotBlank();

        assertThat(candidate.evaluations()).isEmpty();

        // Social networks preserved
        assertThat(candidate.socialNetworks()).hasSize(1);
        assertThat(candidate.socialNetworks().get(0).network()).isEqualTo("linkedin");

        // Relationship ids + labels resolved from `included`
        assertThat(candidate.mainManagerId()).isEqualTo(38837);
        assertThat(candidate.mainManagerName()).isEqualTo("Etienne Mboutsou");
        assertThat(candidate.agencyId()).isEqualTo(1);
        assertThat(candidate.agencyName()).isEqualTo("SIJO");

        // Existing nested structures still mapped
        assertThat(candidate.tools()).hasSize(8);
        assertThat(candidate.languages()).hasSize(3);
    }

    @Test
    void getCandidateDetail_exposesPositioningsStateReasonAndManagers() {
        CandidateDetailDto detail = service.getCandidateDetail(42130);

        assertThat(detail.id()).isEqualTo(42130);
        assertThat(detail.email()).isEqualTo("woshicecile@gmail.com");

        assertThat(detail.numberOfActivePositionings()).isZero();
        assertThat(detail.globalEvaluation()).isEqualTo("-1");
        assertThat(detail.evaluations()).isEmpty();

        assertThat(detail.sourceType()).isEqualTo(-1);
        assertThat(detail.sourceDetail()).isEqualTo("Collective");

        assertThat(detail.stateReasonType()).isZero();
        assertThat(detail.stateReasonDetail()).isEmpty();

        assertThat(detail.socialNetworks()).hasSize(1);
        assertThat(detail.socialNetworks().get(0).url()).contains("linkedin");

        assertThat(detail.mainManagerId()).isEqualTo(38837);
        assertThat(detail.mainManagerName()).isEqualTo("Etienne Mboutsou");
        assertThat(detail.hrManagerId()).isEqualTo(38837);
        assertThat(detail.hrManagerName()).isEqualTo("Etienne Mboutsou");
        assertThat(detail.agencyId()).isEqualTo(1);
        assertThat(detail.agencyName()).isEqualTo("SIJO");
    }

    @Test
    void getCandidateTechnicalDocument_exposesReferencesAndTdLink() {
        TechnicalDocumentDto document = service.getCandidateTechnicalDocument(42130);

        assertThat(document.id()).isEqualTo(42130);
        assertThat(document.tdId()).isEqualTo("42120");
        assertThat(document.tdLink()).isEmpty();
        assertThat(document.title()).contains("Ing");
        assertThat(document.skills()).isNotBlank();

        // Rule 5 — full assignment history preserved
        assertThat(document.references()).hasSize(5);
        ExperienceReference firstReference = document.references().get(0);
        assertThat(firstReference.company()).isEqualTo("Orchestra");
        assertThat(firstReference.description()).contains("plateforme SaaS");

        // Existing nested structures still mapped (tool + numeric proficiency level)
        assertThat(document.tools()).hasSize(8);
        assertThat(document.tools().get(0).tool()).isEqualTo("JAVA");
        assertThat(document.tools().get(0).level()).isZero();
        assertThat(document.languages()).hasSize(3);
    }

    @Test
    void getDictionary_exposesTypeOfResourceAlongsideContract() {
        DictionaryResponseDto dictionary = service.getDictionary();

        // typeOf.resource resolves the candidateTypes filter; previously dropped
        assertThat(dictionary.setting().typeOf().resource()).isNotEmpty();
        assertThat(dictionary.setting().typeOf().contract()).isNotEmpty();
        assertThat(dictionary.setting().state().candidate()).isNotEmpty();
        assertThat(dictionary.setting().availability()).isNotEmpty();
    }

    private Object fixtureForPath(String path) {
        if (path.equals("/application/dictionary")) {
            return dictionaryEnvelope;
        }
        if (path.endsWith("/information")) {
            return detailEnvelope;
        }
        if (path.endsWith("/technical-data")) {
            return technicalDocumentEnvelope;
        }
        if (path.equals("/candidates")) {
            return searchEnvelope;
        }
        return null;
    }

    private <T> T readFixture(String name, TypeReference<T> type) throws IOException {
        try (InputStream in = getClass().getClassLoader().getResourceAsStream("fixtures/" + name)) {
            assertThat(in).as("fixture %s must exist on the test classpath", name).isNotNull();
            return mapper.readValue(in, type);
        }
    }

    private static CandidateSearchRequestDto emptyRequest() {
        return new CandidateSearchRequestDto(
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null);
    }
}
