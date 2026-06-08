package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.exception.BoondApiException;
import org.springframework.http.HttpStatus;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import com.sijo.mcpboondmanager.support.TestFixtures;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.tool.annotation.Tool;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.RecordComponent;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CandidateDetailToolTest {

    @Mock
    private BoondManagerCandidateService candidateService;

    @Test
    void givenCandidateId_whenGetCandidateDetail_thenReturnsServiceResponse() {
        CandidateDetailDto expected = TestFixtures.candidateDetail();
        when(candidateService.getCandidateDetail(42)).thenReturn(expected);

        CandidateDetailDto response = tool().getCandidateDetail(42, true);

        assertThat(response).isSameAs(expected);
        verify(candidateService).getCandidateDetail(42);
        verifyNoMoreInteractions(candidateService);
    }

    @Test
    void givenNoIncludeNotes_whenGetCandidateDetail_thenKeepsNotesByDefault() {
        CandidateDetailDto expected = TestFixtures.candidateDetail();
        when(candidateService.getCandidateDetail(42)).thenReturn(expected);

        CandidateDetailDto response = tool().getCandidateDetail(42, null);

        // includeNotes defaults to true — same instance returned, notes intact.
        assertThat(response).isSameAs(expected);
        assertThat(response.informationComment()).isNotBlank();
    }

    @Test
    void givenIncludeNotesFalse_whenGetCandidateDetail_thenStripsNotesOnly() {
        CandidateDetailDto backend = TestFixtures.candidateDetail();
        when(candidateService.getCandidateDetail(42)).thenReturn(backend);

        CandidateDetailDto response = tool().getCandidateDetail(42, false);

        assertThat(response.informationComment()).isNull();
        // Every other field is preserved.
        assertThat(response.id()).isEqualTo(backend.id());
        assertThat(response.firstName()).isEqualTo(backend.firstName());
        assertThat(response.email()).isEqualTo(backend.email());
        assertThat(response.state()).isEqualTo(backend.state());
        assertThat(response.globalEvaluation()).isEqualTo(backend.globalEvaluation());
        assertThat(response.mainManagerName()).isEqualTo(backend.mainManagerName());
        assertThat(response.hrManagerName()).isEqualTo(backend.hrManagerName());
        assertThat(response.agencyName()).isEqualTo(backend.agencyName());
        assertThat(response.creationSource()).isEqualTo(backend.creationSource());
    }

    @Test
    void givenNullCandidateId_whenGetCandidateDetail_thenDelegatesCurrentServiceBehavior() {
        CandidateDetailDto expected = TestFixtures.candidateDetail();
        when(candidateService.getCandidateDetail(null)).thenReturn(expected);

        CandidateDetailDto response = tool().getCandidateDetail(null, true);

        assertThat(response).isSameAs(expected);
        verify(candidateService).getCandidateDetail(null);
    }

    @Test
    void givenNotFoundException_whenGetCandidateDetail_thenPropagatesException() {
        RuntimeException exception = new RuntimeException("Candidate not found in BoondManager: 42");
        when(candidateService.getCandidateDetail(42)).thenThrow(exception);

        assertThatThrownBy(() -> tool().getCandidateDetail(42, true))
                .isSameAs(exception);
    }

    @Test
    void givenBackendException_whenGetCandidateDetail_thenPropagatesProjectException() {
        BoondApiException exception = new BoondApiException(
                "backend failed", HttpStatus.INTERNAL_SERVER_ERROR, "/candidates/42", new RuntimeException());
        when(candidateService.getCandidateDetail(42)).thenThrow(exception);

        assertThatThrownBy(() -> tool().getCandidateDetail(42, true))
                .isSameAs(exception);
    }

    @Test
    void givenToolClass_whenInspected_thenToolNameRemainsUnchanged() throws NoSuchMethodException {
        Tool annotation = CandidateDetailTool.class
                .getMethod("getCandidateDetail", Integer.class, Boolean.class)
                .getAnnotation(Tool.class);

        assertThat(annotation.name()).isEqualTo("getCandidateDetail");
    }

    @Test
    void givenToolDescription_whenInspected_thenDocumentsEveryReturnedField() {
        Method method = Arrays.stream(CandidateDetailTool.class.getMethods())
                .filter(m -> m.getName().equals("getCandidateDetail"))
                .findFirst()
                .orElseThrow();
        String description = method.getAnnotation(Tool.class).description();

        for (RecordComponent component : CandidateDetailDto.class.getRecordComponents()) {
            assertThat(description)
                    .as("@Tool description should document the returned field '%s'", component.getName())
                    .contains(component.getName());
        }
        assertThat(description).contains("includeNotes");
    }

    @Test
    void givenToolClass_whenInspected_thenDoesNotDependOnBoondManagerClientDirectly() {
        assertThat(Arrays.stream(CandidateDetailTool.class.getDeclaredFields()).map(Field::getType))
                .contains(BoondManagerCandidateService.class)
                .doesNotContain(BoondManagerClient.class);
    }

    private CandidateDetailTool tool() {
        return new CandidateDetailTool(candidateService);
    }
}
