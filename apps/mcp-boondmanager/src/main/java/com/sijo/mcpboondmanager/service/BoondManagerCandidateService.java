package com.sijo.mcpboondmanager.service;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateDetailAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateSummaryAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondData;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionarySetting;
import com.sijo.mcpboondmanager.dto.boond.BoondListEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondMeta;
import com.sijo.mcpboondmanager.dto.boond.BoondSingleEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondTechnicalDocumentAttributes;
import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSummaryDto;
import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
import com.sijo.mcpboondmanager.dto.common.PaginationMetaDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionarySettingDto;
import com.sijo.mcpboondmanager.exception.BoondApiException;
import com.sijo.mcpboondmanager.exception.CandidateNotFoundException;
import com.sijo.mcpboondmanager.exception.DictionaryResolutionException;
import com.sijo.mcpboondmanager.exception.ExternalServiceException;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.util.UriBuilder;

import java.util.List;
import java.util.function.Consumer;

@Service
public class BoondManagerCandidateService {

    static final String DICTIONARY_PATH = "/application/dictionary";
    static final String CANDIDATES_PATH = "/candidates";

    private static final ParameterizedTypeReference<BoondDictionaryEnvelope> DICTIONARY_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondListEnvelope<BoondCandidateSummaryAttributes>> SEARCH_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondSingleEnvelope<BoondCandidateDetailAttributes>> DETAIL_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondSingleEnvelope<BoondTechnicalDocumentAttributes>> TD_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondListEnvelope<BoondTechnicalDocumentAttributes>> TD_LIST_TYPE =
            new ParameterizedTypeReference<>() {};

    private final BoondManagerClient client;
    private final ExperienceDictionaryResolver experienceResolver;

    public BoondManagerCandidateService(BoondManagerClient client,
                                        ExperienceDictionaryResolver experienceResolver) {
        this.client = client;
        this.experienceResolver = experienceResolver;
    }

    public DictionaryResponseDto getDictionary() {
        return getDictionary(null);
    }

    /**
     * @param language optional BoondManager locale to request localized labels (e.g. {@code "en"},
     *                 {@code "fr"}); when {@code null}/blank the account default language is used
     */
    public DictionaryResponseDto getDictionary(String language) {
        try {
            BoondDictionaryEnvelope envelope = client.get(
                    DICTIONARY_PATH,
                    builder -> addScalar(builder, "language", emptyToNull(language)),
                    DICTIONARY_TYPE);
            return toDictionaryResponse(envelope);
        } catch (BoondApiException ex) {
            throw new DictionaryResolutionException(
                    "Failed to resolve BoondManager dictionary", ex.status(), ex.path(), ex);
        }
    }

    public CandidateSearchResponseDto searchCandidates(CandidateSearchRequestDto request) {
        Consumer<UriBuilder> queryParams = builder -> {
            addScalar(builder, "keywords", request.keywords());
            addScalar(builder, "keywordsType", request.keywordsType());
            addList(builder, "candidateStates", request.candidateStates());
            addList(builder, "candidateTypes", request.candidateTypes());
            addList(builder, "availabilityTypes", request.availabilityTypes());
            addList(builder, "contractTypes", request.contractTypes());
            addList(builder, "experiences", request.experiences());
            addList(builder, "expertiseAreas", request.expertiseAreas());
            addList(builder, "activityAreas", request.activityAreas());
            addScalar(builder, "mobilityAreas", request.mobilityAreas());
            addList(builder, "languages", request.languages());
            addList(builder, "tools", request.tools());
            addList(builder, "evaluations", request.evaluations());
            addList(builder, "sources", request.sources());
            addList(builder, "shields", request.shields());
            addScalar(builder, "location", request.location());
            addScalar(builder, "coordinates", request.coordinates());
            addScalar(builder, "geoDistance", request.geoDistance());
            addScalar(builder, "period", request.period());
            addScalar(builder, "startDate", request.startDate());
            addScalar(builder, "endDate", request.endDate());
            addScalar(builder, "periodDynamic", request.periodDynamic());
            addScalar(builder, "page", request.page());
            addScalar(builder, "maxResults", request.maxResults());
            addList(builder, "sort", request.sort());
            addScalar(builder, "order", request.order());
            addList(builder, "columns", request.columns());
        };
        BoondListEnvelope<BoondCandidateSummaryAttributes> envelope =
                client.get(CANDIDATES_PATH, queryParams, SEARCH_TYPE);
        return toSearchResponse(envelope);
    }

    public CandidateDetailDto getCandidateDetail(Integer candidateId) {
        String path = CANDIDATES_PATH + "/" + candidateId + "/information";
        try {
            BoondSingleEnvelope<BoondCandidateDetailAttributes> envelope =
                    client.get(path, DETAIL_TYPE);
            return toCandidateDetail(envelope);
        } catch (BoondApiException ex) {
            if (HttpStatus.NOT_FOUND.value() == ex.status().value()) {
                throw new CandidateNotFoundException(candidateId, path, ex);
            }
            throw ex;
        }
    }

    public TechnicalDocumentDto getCandidateTechnicalDocument(Integer candidateId) {
        String path = CANDIDATES_PATH + "/" + candidateId + "/technical-data";
        String fallbackPath = CANDIDATES_PATH + "/" + candidateId + "/technical-datas";
        try {
            return getCandidateTechnicalDocumentAtPath(path);
        } catch (BoondApiException | ExternalServiceException ex) {
            try {
                return getCandidateTechnicalDocumentAtPath(fallbackPath);
            } catch (BoondApiException | ExternalServiceException fallbackEx) {
                if (isNotFound(fallbackEx)) {
                    if (!isNotFound(ex)) {
                        throw ex;
                    }
                    throw new CandidateNotFoundException(candidateId, fallbackPath, fallbackEx);
                }
                throw fallbackEx;
            }
        }
    }

    private static boolean isNotFound(RuntimeException ex) {
        return ex instanceof BoondApiException boondEx
                && HttpStatus.NOT_FOUND.value() == boondEx.status().value();
    }

    private TechnicalDocumentDto getCandidateTechnicalDocumentAtPath(String path) {
        try {
            BoondSingleEnvelope<BoondTechnicalDocumentAttributes> envelope =
                    client.get(path, TD_TYPE);
            return toTechnicalDocument(envelope);
        } catch (ExternalServiceException ex) {
            BoondListEnvelope<BoondTechnicalDocumentAttributes> envelope =
                    client.get(path, TD_LIST_TYPE);
            return toTechnicalDocument(envelope);
        }
    }

    /**
     * Appends a scalar query parameter ({@code name=value}); skips null values.
     */
    private static void addScalar(UriBuilder builder, String name, Object value) {
        if (value != null) {
            builder.queryParam(name, value);
        }
    }

    /**
     * Returns {@code null} for a {@code null}/blank string, so it is skipped by {@link #addScalar}.
     */
    private static String emptyToNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }

    /**
     * Appends a repeatable query parameter as multiple {@code name[]=value} entries (BoondManager
     * unions multiple values). Skips null/empty lists and null elements — never sends an empty list.
     */
    private static void addList(UriBuilder builder, String name, List<?> values) {
        if (values == null || values.isEmpty()) {
            return;
        }
        for (Object value : values) {
            if (value != null) {
                builder.queryParam(name + "[]", value);
            }
        }
    }

    private static DictionaryResponseDto toDictionaryResponse(BoondDictionaryEnvelope envelope) {
        BoondDictionarySetting setting = envelope.data().setting();
        return new DictionaryResponseDto(new DictionarySettingDto(
                new DictionarySettingDto.State(setting.state().candidate()),
                new DictionarySettingDto.TypeOf(setting.typeOf().contract()),
                setting.availability(),
                setting.mobilityArea(),
                setting.experience(),
                setting.training(),
                setting.expertiseArea(),
                setting.activityArea(),
                setting.tool(),
                setting.languageSpoken(),
                setting.languageLevel(),
                setting.evaluation(),
                setting.source()
        ));
    }

    private CandidateSearchResponseDto toSearchResponse(
            BoondListEnvelope<BoondCandidateSummaryAttributes> envelope) {
        List<CandidateSummaryDto> candidates = envelope.data().stream()
                .map(this::toCandidateSummary)
                .toList();
        return new CandidateSearchResponseDto(candidates, toPaginationMeta(envelope.meta()));
    }

    private CandidateSummaryDto toCandidateSummary(BoondData<BoondCandidateSummaryAttributes> data) {
        BoondCandidateSummaryAttributes attrs = data.attributes();
        ResolvedExperience experience = experienceResolver.resolve(attrs.experience());
        return new CandidateSummaryDto(
                parseId(data.id()),
                attrs.firstName(),
                attrs.lastName(),
                attrs.email1(),
                attrs.state(),
                attrs.availability(),
                attrs.typeOf(),
                attrs.mobilityAreas(),
                attrs.town(),
                attrs.country(),
                attrs.title(),
                attrs.experience(),
                experience.minYears(),
                experience.openEnded(),
                experience.specified(),
                experience.rawLabel(),
                attrs.skills(),
                attrs.diplomas(),
                attrs.expertiseAreas(),
                attrs.activityAreas(),
                toToolProficiencies(attrs.tools()),
                toLanguageProficiencies(attrs.languages())
        );
    }

    private static CandidateDetailDto toCandidateDetail(
            BoondSingleEnvelope<BoondCandidateDetailAttributes> envelope) {
        BoondData<BoondCandidateDetailAttributes> data = envelope.data();
        BoondCandidateDetailAttributes a = data.attributes();
        BoondCandidateDetailAttributes.Source source = a.source();
        Integer sourceType = source == null ? null : source.typeOf();
        String sourceDetail = source == null ? null : source.detail();
        return new CandidateDetailDto(
                parseId(data.id()),
                a.firstName(),
                a.lastName(),
                a.email1(),
                a.email2(),
                a.email3(),
                a.phone1(),
                a.phone2(),
                a.phone3(),
                a.fax(),
                a.civility(),
                a.dateOfBirth(),
                a.address(),
                a.postcode(),
                a.town(),
                a.country(),
                a.subDivision(),
                a.title(),
                a.initials(),
                a.state(),
                a.typeOf(),
                a.availability(),
                a.mobilityAreas(),
                sourceType,
                sourceDetail,
                a.globalEvaluation(),
                a.informationComments(),
                a.creationDate(),
                a.updateDate(),
                a.creationSource()
        );
    }

    private TechnicalDocumentDto toTechnicalDocument(
            BoondSingleEnvelope<BoondTechnicalDocumentAttributes> envelope) {
        return toTechnicalDocument(envelope.data());
    }

    private TechnicalDocumentDto toTechnicalDocument(
            BoondListEnvelope<BoondTechnicalDocumentAttributes> envelope) {
        if (envelope.data() == null || envelope.data().isEmpty()) {
            throw new ExternalServiceException(
                    "BoondManager returned no technical document records",
                    CANDIDATES_PATH,
                    null);
        }
        return toTechnicalDocument(envelope.data().getFirst());
    }

    private TechnicalDocumentDto toTechnicalDocument(
            BoondData<BoondTechnicalDocumentAttributes> data) {
        BoondTechnicalDocumentAttributes a = data.attributes();
        ResolvedExperience experience = experienceResolver.resolve(a.experience());
        return new TechnicalDocumentDto(
                parseId(data.id()),
                a.tdId(),
                a.title(),
                a.description(),
                a.summary(),
                a.experience(),
                experience.minYears(),
                experience.openEnded(),
                experience.specified(),
                experience.rawLabel(),
                a.training(),
                a.diplomas(),
                a.skills(),
                a.expertiseAreas(),
                a.activityAreas(),
                toToolProficiencies(a.tools()),
                toLanguageProficiencies(a.languages())
        );
    }

    private static List<TechnicalDocumentDto.ToolProficiency> toToolProficiencies(
            List<BoondTechnicalDocumentAttributes.Tool> tools) {
        if (tools == null) {
            return null;
        }
        return tools.stream()
                .map(tool -> new TechnicalDocumentDto.ToolProficiency(tool.tool(), tool.level()))
                .toList();
    }

    private static List<TechnicalDocumentDto.LanguageProficiency> toLanguageProficiencies(
            List<BoondTechnicalDocumentAttributes.Language> languages) {
        if (languages == null) {
            return null;
        }
        return languages.stream()
                .map(language -> new TechnicalDocumentDto.LanguageProficiency(
                        language.language(), language.level()))
                .toList();
    }

    private static PaginationMetaDto toPaginationMeta(BoondMeta meta) {
        Integer rows = meta.totals() == null ? null : meta.totals().rows();
        return new PaginationMetaDto(rows, meta.currentPage());
    }

    private static Integer parseId(String id) {
        return id == null ? null : Integer.valueOf(id);
    }
}
