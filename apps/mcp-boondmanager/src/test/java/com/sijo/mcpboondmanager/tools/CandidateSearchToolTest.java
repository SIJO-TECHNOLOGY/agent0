package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSummaryDto;
import com.sijo.mcpboondmanager.dto.candidate.ExperienceReference;
import com.sijo.mcpboondmanager.exception.BoondApiException;
import org.springframework.http.HttpStatus;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import com.sijo.mcpboondmanager.support.TestFixtures;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.tool.annotation.Tool;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.RecordComponent;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CandidateSearchToolTest {

    @Mock
    private BoondManagerCandidateService candidateService;

    @Test
    void givenQueryOnly_whenSearchCandidates_thenDelegatesWithKeywordRequest() {
        CandidateSearchResponseDto expected = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(expected);

        CandidateSearchResponseDto response = tool().searchCandidates(
                "java",
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null,
                true
        );

        assertThat(response).isSameAs(expected);
        ArgumentCaptor<CandidateSearchRequestDto> requestCaptor =
                ArgumentCaptor.forClass(CandidateSearchRequestDto.class);
        verify(candidateService).searchCandidates(requestCaptor.capture());
        assertThat(requestCaptor.getValue().keywords()).isEqualTo("java");
        assertThat(requestCaptor.getValue().candidateStates()).isNull();
        assertThat(requestCaptor.getValue().maxResults()).isNull();
        verifyNoMoreInteractions(candidateService);
    }

    @Test
    void givenFilters_whenSearchCandidates_thenDelegatesWithAllFilters() {
        CandidateSearchResponseDto expected = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(expected);

        CandidateSearchResponseDto response = tool().searchCandidates(
                "java",
                "resumeTd",
                List.of(2, 5),
                null,
                List.of(9),
                List.of(1),
                List.of(3),
                List.of("backend", "microservices"),
                List.of("profilsdeveloppeur"),
                "idf",
                List.of("anglais|courant"),
                List.of("JAVA"),
                List.of("4"),
                List.of("4"),
                List.of("complete"),
                "Paris",
                null,
                50,
                "updated",
                "2026-01-01",
                "2026-06-01",
                null,
                1,
                25,
                List.of("updateDate"),
                "desc",
                List.of("name", "title", "state", "availability", "expertiseAreas", "experience"),
                true
        );

        assertThat(response).isSameAs(expected);
        ArgumentCaptor<CandidateSearchRequestDto> requestCaptor =
                ArgumentCaptor.forClass(CandidateSearchRequestDto.class);
        verify(candidateService).searchCandidates(requestCaptor.capture());
        assertThat(requestCaptor.getValue())
                .usingRecursiveComparison()
                .isEqualTo(TestFixtures.searchRequest());
    }

    @Test
    void givenEmptyQuery_whenSearchCandidates_thenDelegatesAccordingToOptionalDtoRules() {
        CandidateSearchResponseDto expected = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(expected);

        CandidateSearchResponseDto response = tool().searchCandidates(
                "",
                null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null,
                1,
                25,
                null, null, null,
                true
        );

        assertThat(response).isSameAs(expected);
        ArgumentCaptor<CandidateSearchRequestDto> requestCaptor =
                ArgumentCaptor.forClass(CandidateSearchRequestDto.class);
        verify(candidateService).searchCandidates(requestCaptor.capture());
        assertThat(requestCaptor.getValue().keywords()).isEmpty();
        assertThat(requestCaptor.getValue().page()).isEqualTo(1);
        assertThat(requestCaptor.getValue().maxResults()).isEqualTo(25);
    }

    @Test
    void givenIncludeResumeTrue_whenSearchCandidates_thenReturnsFullResultUnchanged() {
        CandidateSearchResponseDto expected = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(expected);

        CandidateSearchResponseDto response = search(true);

        // includeResume=true is a pure passthrough — same instance, free text intact.
        assertThat(response).isSameAs(expected);
        CandidateSummaryDto candidate = response.candidates().getFirst();
        assertThat(candidate.skills()).isNotBlank();
        ExperienceReference reference = candidate.references().getFirst();
        assertThat(reference.skills()).isNotBlank();
        assertThat(reference.description()).isNotBlank();
    }

    @Test
    void givenIncludeResumeFalse_whenSearchCandidates_thenStripsResumeFreeText() {
        CandidateSearchResponseDto backend = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(backend);

        CandidateSearchResponseDto response = search(false);

        CandidateSummaryDto candidate = response.candidates().getFirst();
        assertThat(candidate.skills()).isNull();
        ExperienceReference reference = candidate.references().getFirst();
        assertThat(reference.skills()).isNull();
        assertThat(reference.description()).isNull();
        // Everything else is preserved — only the free text is gated.
        CandidateSummaryDto original = TestFixtures.candidateSummary();
        ExperienceReference originalReference = original.references().getFirst();
        assertThat(candidate.firstName()).isEqualTo(original.firstName());
        assertThat(candidate.title()).isEqualTo(original.title());
        assertThat(candidate.diplomas()).isEqualTo(original.diplomas());
        assertThat(reference.title()).isEqualTo(originalReference.title());
        assertThat(reference.company()).isEqualTo(originalReference.company());
        assertThat(reference.startYear()).isEqualTo(originalReference.startYear());
        assertThat(response.meta()).isEqualTo(backend.meta());
    }

    @Test
    void givenNoIncludeResume_whenSearchCandidates_thenDefaultsToStripped() {
        CandidateSearchResponseDto backend = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(backend);

        CandidateSearchResponseDto response = search(null);

        CandidateSummaryDto candidate = response.candidates().getFirst();
        assertThat(candidate.skills()).isNull();
        assertThat(candidate.references().getFirst().skills()).isNull();
        assertThat(candidate.references().getFirst().description()).isNull();
    }

    @Test
    void givenBackendException_whenSearchCandidates_thenPropagatesProjectException() {
        BoondApiException exception = new BoondApiException(
                "backend failed", HttpStatus.INTERNAL_SERVER_ERROR, "/candidates", new RuntimeException());
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenThrow(exception);

        assertThatThrownBy(() -> search(null)).isSameAs(exception);
    }

    @Test
    void givenToolClass_whenInspected_thenToolNameRemainsUnchanged() throws NoSuchMethodException {
        Tool annotation = CandidateSearchTool.class.getMethod(
                "searchCandidates",
                String.class,        // keywords
                String.class,        // keywordsType
                List.class,          // candidateStates
                List.class,          // candidateTypes
                List.class,          // availabilityTypes
                List.class,          // contractTypes
                List.class,          // experiences
                List.class,          // expertiseAreas
                List.class,          // activityAreas
                String.class,        // mobilityAreas
                List.class,          // languages
                List.class,          // tools
                List.class,          // evaluations
                List.class,          // sources
                List.class,          // shields
                String.class,        // location
                String.class,        // coordinates
                Integer.class,       // geoDistance
                String.class,        // period
                String.class,        // startDate
                String.class,        // endDate
                String.class,        // periodDynamic
                Integer.class,       // page
                Integer.class,       // maxResults
                List.class,          // sort
                String.class,        // order
                List.class,          // columns
                Boolean.class        // includeResume
        ).getAnnotation(Tool.class);

        assertThat(annotation.name()).isEqualTo("searchCandidates");
    }

    @Test
    void givenToolDescription_whenInspected_thenDocumentsEveryReturnedSummaryField() {
        Method method = Arrays.stream(CandidateSearchTool.class.getMethods())
                .filter(m -> m.getName().equals("searchCandidates"))
                .findFirst()
                .orElseThrow();
        String description = method.getAnnotation(Tool.class).description();

        for (RecordComponent component : CandidateSummaryDto.class.getRecordComponents()) {
            assertThat(description)
                    .as("@Tool description should document the returned field '%s'", component.getName())
                    .contains(component.getName());
        }
        assertThat(description).contains("includeResume");
    }

    @Test
    void givenToolClass_whenInspected_thenDoesNotDependOnBoondManagerClientDirectly() {
        assertThat(Arrays.stream(CandidateSearchTool.class.getDeclaredFields()).map(Field::getType))
                .contains(BoondManagerCandidateService.class)
                .doesNotContain(BoondManagerClient.class);
    }

    private CandidateSearchResponseDto search(Boolean includeResume) {
        return tool().searchCandidates(
                "java",
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null,
                includeResume
        );
    }

    private CandidateSearchTool tool() {
        return new CandidateSearchTool(candidateService);
    }
}
