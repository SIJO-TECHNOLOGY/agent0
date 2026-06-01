package com.sijo.mcpboondmanager.dto;

import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryEntryDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionarySettingDto;
import com.sijo.mcpboondmanager.support.TestFixtures;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class DtoValidationTest {

    private static ValidatorFactory validatorFactory;
    private static Validator validator;

    @BeforeAll
    static void setUpValidator() {
        validatorFactory = Validation.buildDefaultValidatorFactory();
        validator = validatorFactory.getValidator();
    }

    @AfterAll
    static void closeValidator() {
        validatorFactory.close();
    }

    @Test
    void givenValidSearchRequest_whenValidated_thenNoViolations() {
        Set<ConstraintViolation<CandidateSearchRequestDto>> violations =
                validator.validate(TestFixtures.searchRequest());

        assertThat(violations).isEmpty();
    }

    @Test
    void givenOptionalSearchRequestFieldsAreNull_whenValidated_thenNoViolations() {
        CandidateSearchRequestDto request = new CandidateSearchRequestDto(
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null
        );

        Set<ConstraintViolation<CandidateSearchRequestDto>> violations = validator.validate(request);

        assertThat(violations).isEmpty();
    }

    @Test
    void givenPageBelowMinimum_whenValidated_thenPageViolationIsReturned() {
        CandidateSearchRequestDto request = searchRequestWithPageAndLimit(0, 25);

        Set<ConstraintViolation<CandidateSearchRequestDto>> violations = validator.validate(request);

        assertThat(propertyPaths(violations)).containsExactly("page");
    }

    @Test
    void givenLimitBelowMinimum_whenValidated_thenLimitViolationIsReturned() {
        CandidateSearchRequestDto request = searchRequestWithPageAndLimit(1, 0);

        Set<ConstraintViolation<CandidateSearchRequestDto>> violations = validator.validate(request);

        assertThat(propertyPaths(violations)).containsExactly("maxResults");
    }

    @Test
    void givenLimitAboveMaximum_whenValidated_thenLimitViolationIsReturned() {
        CandidateSearchRequestDto request = searchRequestWithPageAndLimit(1, 501);

        Set<ConstraintViolation<CandidateSearchRequestDto>> violations = validator.validate(request);

        assertThat(propertyPaths(violations)).containsExactly("maxResults");
    }

    @Test
    void givenSupportedLanguageDictionaryEntries_whenValidated_thenNoViolations() {
        DictionaryResponseDto response = new DictionaryResponseDto(new DictionarySettingDto(
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                List.of(
                        new DictionaryEntryDto("fr", "French"),
                        new DictionaryEntryDto("en", "English"),
                        new DictionaryEntryDto("es", "Spanish")
                ),
                null,
                null,
                null
        ));

        Set<ConstraintViolation<DictionaryResponseDto>> violations = validator.validate(response);

        assertThat(violations).isEmpty();
    }

    @Test
    void givenBackendResponseDtos_whenValidated_thenNoViolations() {
        assertThat(validator.validate(TestFixtures.searchResponse())).isEmpty();
        assertThat(validator.validate(TestFixtures.candidateDetail())).isEmpty();
        assertThat(validator.validate(TestFixtures.technicalDocument())).isEmpty();
        assertThat(validator.validate(TestFixtures.dictionary())).isEmpty();
    }

    private CandidateSearchRequestDto searchRequestWithPageAndLimit(Integer page, Integer maxResults) {
        CandidateSearchRequestDto request = TestFixtures.searchRequest();
        return new CandidateSearchRequestDto(
                request.keywords(),
                request.keywordsType(),
                request.candidateStates(),
                request.candidateTypes(),
                request.availabilityTypes(),
                request.contractTypes(),
                request.experiences(),
                request.expertiseAreas(),
                request.activityAreas(),
                request.mobilityAreas(),
                request.languages(),
                request.tools(),
                request.evaluations(),
                request.sources(),
                request.shields(),
                request.location(),
                request.coordinates(),
                request.geoDistance(),
                request.period(),
                request.startDate(),
                request.endDate(),
                request.periodDynamic(),
                page,
                maxResults,
                request.sort(),
                request.order(),
                request.columns()
        );
    }

    private List<String> propertyPaths(Set<? extends ConstraintViolation<?>> violations) {
        return violations.stream()
                .map(violation -> violation.getPropertyPath().toString())
                .sorted()
                .toList();
    }
}
