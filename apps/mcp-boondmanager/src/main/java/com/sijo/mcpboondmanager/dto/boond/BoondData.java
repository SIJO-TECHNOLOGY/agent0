package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * A JSON:API resource node ({@code id} + {@code type} + {@code attributes}). The optional
 * {@code relationships} object links the resource to others (managers, agency, …); their names are
 * resolved from the envelope's {@code included} array (see {@link BoondIncluded}). The dictionary
 * endpoint does not use this shape, so {@code relationships} is simply {@code null} there.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondData<A>(
        String id,
        String type,
        A attributes,
        BoondRelationships relationships
) {
}