#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright 2017 National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________
"""
The pyomo.contrib.pynumero.sparse.block_matrix module includes methods that extend
linear algebra operations in scipy for case of structured problems
where linear algebra operations present an inherent block structure.
This interface consider matrices of the form:

m = [[m11, m12],[m21, m22], ..]

where m_{i,j} are sparse matrices

.. rubric:: Contents

"""

from pyomo.contrib.pynumero.sparse.mpi_block_vector import MPIBlockVector
from pyomo.contrib.pynumero.sparse import BlockVector, BlockMatrix
from pyomo.contrib.pynumero.sparse.utils import is_symmetric_sparse
from pyomo.contrib.pynumero.sparse import empty_matrix

from mpi4py import MPI
import numpy as np

# Array classifiers
SINGLE_OWNER=1
MULTIPLE_OWNER=2
ALL_OWN_IT=0


# ALL_OWNED = -1

class MPIBlockMatrix(object):
    """
    Parallel Structured Matrix interface

    Parameters
    -------------------
    nbrows : int
             number of block-rows in the matrix
    nbcols : int
             number of block-columns in the matrix
    rank_ownership: array_like
                    integer 2D array that specifies the rank of process
                    owner of each block in the matrix. For blocks that are
                    owned by all processes the rank is -1. Blocks that are
                    None should be owned by all processes.
    mpi_comm : communicator
    """

    def __init__(self, nbrows, nbcols, rank_ownership, mpi_comm):

        shape = (nbrows, nbcols)
        self._block_matrix = BlockMatrix(nbrows, nbcols)
        self._mpiw = mpi_comm
        self._rank_owner = np.zeros(shape, dtype=np.int64)
        self._owned_mask = np.zeros(shape, dtype=bool)
        self._unique_owned_mask = np.zeros(shape, dtype=bool)

        rank = self._mpiw.Get_rank()

        if isinstance(rank_ownership, list):
            rank_owner_format = 1
        elif isinstance(rank_ownership, np.ndarray):
            rank_owner_format = 2
            assert rank_ownership.ndim == 2, 'rank_ownership must be of size 2'
        else:
            raise RuntimeError('rank_ownership must be a list of lists or a numpy array')

        for i in range(nbrows):
            for j in range(nbcols):

                if rank_owner_format == 1:
                    owner = rank_ownership[i][j]
                else:
                    owner = rank_ownership[i, j]
                assert owner < self._mpiw.Get_size(), \
                    'rank owner out of range'
                self._rank_owner[i, j] = owner
                if rank == owner or owner < 0:
                    self._owned_mask[i, j] = True
                    if owner == rank:
                        self._unique_owned_mask[i, j] = True

        # Note: this requires communication but is disabled when assertions
        # are turned off
        assert self._assert_correct_owners(), \
            'rank_owner must be the same in all processors'

        # classify row ownership
        self._row_type = np.empty(nbrows, dtype=np.int64)
        for i in range(nbrows):
            self._row_type[i] = ALL_OWN_IT
            last_owner = -1
            for j in range(nbcols):
                owner = self._rank_owner[i, j]
                if owner >= 0:
                    if self._row_type[i] == ALL_OWN_IT:
                        last_owner = owner
                        self._row_type[i] = SINGLE_OWNER
                    elif self._row_type[i] == SINGLE_OWNER and owner != last_owner:
                        self._row_type[i] = MULTIPLE_OWNER
                        break

        # classify column ownership
        self._column_type = np.empty(nbcols, dtype=np.int64)
        for j in range(nbcols):
            self._column_type[j] = ALL_OWN_IT
            last_owner = -1
            for i in range(nbrows):
                owner = self._rank_owner[i, j]
                if owner >= 0:
                    if self._column_type[j] == ALL_OWN_IT:
                        last_owner = owner
                        self._column_type[j] = SINGLE_OWNER
                    elif self._column_type[j] == SINGLE_OWNER and owner != last_owner:
                        self._column_type[j] = MULTIPLE_OWNER
                        break


        self._need_setup = True
        self._done_first_setup = False
        self._brow_lengths = np.zeros(nbrows, dtype=np.int64)
        self._bcol_lengths = np.zeros(nbcols, dtype=np.int64)

        # make some of the pointers unmutable
        self._rank_owner.flags.writeable = False # mutable only when needed
        self._owned_mask.flags.writeable = False # mutable only when needed


    @property
    def bshape(self):
        """
        Returns the block-shape of the matrix
        """
        return self._block_matrix.bshape

    @property
    def shape(self):
        """
        Returns tuple with total number of rows and columns
        """
        self._assert_setup()
        return np.sum(self._brow_lengths), np.sum(self._bcol_lengths)

    @property
    def nnz(self):
        """
        Returns total number of nonzero values in the matrix
        """
        local_nnz = 0
        rank = self._mpiw.Get_rank()
        block_indices = self._unique_owned_mask if rank!=0 else self._owned_mask
        ii, jj = np.nonzero(self._owned_mask)
        for i, j in zip(ii, jj):
            if not self._block_matrix.is_empty_block(i, j):
                local_nnz += self._block_matrix[i, j].nnz
        return self._mpiw.allreduce(local_nnz, op=MPI.SUM)

    @property
    def rank_ownership(self):
        """
        Returns 2D array that specifies process rank that owns each blocks
        """
        return self._rank_owner

    @property
    def ownership_mask(self):
        """
        Returns 2D boolean array that indicates which blocks are owned by this process
        """
        return self._owned_mask

    def tocoo(self):
        """
        Converts this matrix to coo_matrix format.

        Returns
        -------
        coo_matrix

        """
        raise RuntimeError('Operation not supported by MPIBlockMatrix')

    def tocsr(self):
        """
        Converts this matrix to csr format.

        Returns
        -------
        csr_matrix

        """
        raise RuntimeError('Operation not supported by MPIBlockMatrix')

    def tocsc(self):
        """
        Converts this matrix to csc format.

        Returns
        -------
        csc_matrix

        """
        raise RuntimeError('Operation not supported by MPIBlockMatrix')

    def tolil(self, copy=False):
        """Convert matrix to LInked List format.
        """
        raise RuntimeError('Operation not supported by MPIBlockMatrix')

    def todia(self, copy=False):
        """Convert this matrix to sparse DIAgonal format.
        """
        raise RuntimeError('Operation not supported by MPIBlockMatrix')

    def tobsr(self, blocksize=None, copy=False):
        """Convert matrix to Block Sparse Row format.
        """
        raise RuntimeError('Operation not supported by MPIBlockMatrix')

    def toarray(self):
        """
        Returns a dense ndarray representation of this matrix.

        Returns
        -------
        arr : ndarray, 2-dimensional
            An array with the same shape and containing the same data
            represented by the block matrix.

        """
        raise RuntimeError('Operation not supported by MPIBlockMatrix')

    def todense(self):
        """
        Returns a dense matrix representation of this matrix.

        Returns
        -------
        arr : ndarray, 2-dimensional
            An array with the same shape and containing the same data
            represented by the block matrix.

        """
        raise RuntimeError('Operation not supported by MPIBlockMatrix')

    def is_empty_block(self, idx, jdx):
        """
        Indicates if a block is empty

        Parameters
        ----------
        idx: int
            block-row index
        jdx: int
            block-column index

        Returns
        -------
        boolean

        """
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    # Note: this requires communication
    def setup(self):
        rank = self._mpiw.Get_rank()
        num_processors = self._mpiw.Get_size()

        local_row_data = self._block_matrix.row_block_sizes()
        local_col_data = self._block_matrix.col_block_sizes()
        send_data = np.concatenate([local_row_data, local_col_data])

        receive_data = np.empty(num_processors * (self.bshape[0] + self.bshape[1]),
                                dtype=np.int64)

        self._mpiw.Allgather(send_data, receive_data)

        proc_dims = np.split(receive_data, num_processors)
        m, n = self.bshape

        # check the rows
        for i in range(m):
            rows_length = set()
            for k in range(num_processors):
                row_sizes, col_sizes = np.split(proc_dims[k],
                                                [self.bshape[0]])
                rows_length.add(row_sizes[i])
            if len(rows_length)>2:
                msg = 'Row {} has more than one dimension accross processors'.format(i)
                raise RuntimeError(msg)
            elif len(rows_length) == 2:
                if 0 not in rows_length:
                    msg = 'Row {} has more than one dimension accross processors'.format(i)
                    raise RuntimeError(msg)
                rows_length.remove(0)

            # here rows_length must only have one element
            self._brow_lengths[i] = rows_length.pop()

        # check columns
        for i in range(n):
            cols_length = set()
            for k in range(num_processors):
                rows_sizes, col_sizes = np.split(proc_dims[k],
                                                 [self.bshape[0]])
                cols_length.add(col_sizes[i])
            if len(cols_length)>2:
                msg = 'Column {} has more than one dimension accross processors'.format(i)
                raise RuntimeError(msg)
            elif len(cols_length) == 2:
                if 0 not in cols_length:
                    msg = 'Column {} has more than one dimension accross processors'.format(i)
                    raise RuntimeError(msg)
                cols_length.remove(0)

            # here rows_length must only have one element
            self._bcol_lengths[i] = cols_length.pop()

        self._need_setup = False
        self._done_first_setup = True

    def row_block_sizes(self, copy=True):
        """
        Returns row-block sizes

        Returns
        -------
        ndarray

        """
        self._assert_setup()
        if copy:
            return np.copy(self._brow_lengths)
        return self._brow_lengths

    def col_block_sizes(self, copy=True):
        """
        Returns col-block sizes

        Returns
        -------
        narray

        """
        self._assert_setup()
        if copy:
            return np.copy(self._bcol_lengths)
        self._bcol_lengths

    def block_shapes(self):
        """
        Returns shapes of blocks in BlockMatrix

        Returns
        -------
        list
        """
        self._assert_setup()
        bm, bn = self.bshape
        sizes = [list() for i in range(bm)]
        for i in range(bm):
            sizes[i] = list()
            for j in range(bn):
                shape = self._brow_lengths[i], self._bcol_lengths[j]
                sizes[i].append(shape)
        return sizes

    def has_empty_rows(self):
        """
        Indicates if the matrix has block-rows that are empty

        Returns
        -------
        boolean

        """
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def has_empty_cols(self):
        """
        Indicates if the matrix has block-columns that are empty

        Returns
        -------
        boolean

        """
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def reset_bcol(self, jdx):
        """
        Resets all blocks in selected column to None

        Parameters
        ----------
        idx: integer
            column index to be reset

        Returns
        -------
        None

        """
        m, n = self.bshape
        assert 0 <= jdx < n, 'Index out of bounds'
        for idx in range(m):
            self[idx, jdx] = None

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def reset_brow(self, idx):
        """
        Resets all blocks in selected row to None

        Parameters
        ----------
        idx: integer
            row index to be reset

        Returns
        -------
        None

        """
        m, n = self.bshape
        assert 0 <= idx < m, 'Index out of bounds'
        for jdx in range(n):
            self[idx, jdx] = None

    def copy(self):
        m, n = self.bshape
        result = MPIBlockMatrix(m, n, self._rank_owner, self._mpiw)
        result._block_matrix = self._block_matrix.copy()
        result._need_setup = self._need_setup
        result._done_first_setup = self._done_first_setup
        result._brow_lengths = self._brow_lengths.copy()
        result._bcol_lengths = self._bcol_lengths.copy()
        return result

    def copy_structure(self):
        m, n = self.bshape
        result = MPIBlockMatrix(m, n, self._rank_owner, self._mpiw)
        result._block_matrix = self._block_matrix.copy_structure()
        result._need_setup = self._need_setup
        result._done_first_setup = self._done_first_setup
        result._brow_lengths = self._brow_lengths.copy()
        result._bcol_lengths = self._bcol_lengths.copy()
        return result

    def _assert_setup(self):

        if not self._done_first_setup:
            assert not self._need_setup, \
                'First need to call setup()'
        else:
            assert not self._need_setup, \
                'Changes in structure. Need to recall setup()'

    # Note: this requires communication
    def _assert_correct_owners(self, root=0):

        rank = self._mpiw.Get_rank()
        num_processors = self._mpiw.Get_size()

        if num_processors == 1:
            return True

        local_owners = self._rank_owner.copy().flatten()
        flat_size = self.bshape[0] * self.bshape[1]
        receive_data = None
        if rank == root:
            receive_data = np.empty(flat_size * num_processors, dtype=np.int64)
        self._mpiw.Gather(local_owners, receive_data, root=root)

        if rank == root:
            owners_in_processor = np.split(receive_data, num_processors)
            root_rank_owners = owners_in_processor[root]
            for i in range(flat_size):
                for k in range(num_processors):
                    if k != root:
                        if owners_in_processor[root][i] != root_rank_owners[i]:
                            return False
        return True

    def __repr__(self):
        return '{}{}'.format(self.__class__.__name__, self.shape)

    def pprint(self):
        self._assert_setup()
        msg = self.__repr__() + '\n'
        num_processors = self._mpiw.Get_size()
        # figure out which ones are none
        local_mask = self._block_matrix._block_mask.copy().flatten()
        receive_data = np.empty(num_processors * local_mask.size,
                                dtype=np.bool)

        self._mpiw.Allgather(local_mask, receive_data)
        all_masks = np.split(receive_data, num_processors)
        m, n = self.bshape
        matrix_maks = [mask.reshape(m, n) for mask in all_masks]

        global_mask = np.zeros((m, n), dtype=np.bool)
        for k in range(num_processors):
            for idx in range(m):
                for jdx in range(n):
                    global_mask[idx, jdx] += matrix_maks[k][idx, jdx]

        for idx in range(m):
            for jdx in range(n):
                rank = self._rank_owner[idx, jdx] if self._rank_owner[idx, jdx] >= 0 else 'A'
                row_size = self._brow_lengths[idx]
                col_size = self._bcol_lengths[jdx]
                is_none = '' if global_mask[idx, jdx] else '*'
                repn = 'Owned_by {} Shape({},{}){}'.format(rank,
                                                           row_size,
                                                           col_size,
                                                           is_none)
                msg += '({}, {}): {}\n'.format(idx, jdx, repn)
        print(msg)

    def __getitem__(self, item):

        block = self._block_matrix[item]
        owner = self._rank_owner[item]
        rank = self._mpiw.Get_rank()
        assert owner == rank or \
               owner < 0, \
               'Block {} not owned by processor {}'.format(item, rank)

        return block

    def __setitem__(self, key, value):

        assert not isinstance(key, slice), \
            'Slices not supported in BlockMatrix'
        assert isinstance(key, tuple), \
            'Indices must be tuples (i,j)'

        idx, jdx = key
        assert idx >= 0 and \
               jdx >= 0, 'Indices must be positive'

        assert idx < self.bshape[0] and \
               jdx < self.bshape[1], 'Indices out of range'

        owner = self._rank_owner[key]
        rank = self._mpiw.Get_rank()
        assert owner == rank or \
               owner < 0, \
               'Block {} not owned by processor {}'.format(key, rank)

        # Flag broadcasting if needed
        if value is None:
            if self._block_matrix[key] is not None:
                self._need_setup = True
        else:
            m, n  = value.shape
            if self._brow_lengths[idx] != m or self._bcol_lengths[jdx] != n:
                self._need_setup = True

        self._block_matrix[key] = value

    def __add__(self, other):

        # ToDo: this might not be needed
        self._assert_setup()
        m, n = self.bshape
        result = self.copy_structure()

        rank = self._mpiw.Get_rank()

        if isinstance(other, MPIBlockMatrix):

            # ToDo: this might not be needed
            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1 + mat2
                elif mat1 is not None and mat2 is None:
                    result[i, j] = mat1
                elif mat1 is None and mat2 is not None:
                    result[i, j] = mat2
                else:
                    result[i, j] = None
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1 + mat2
                elif mat1 is not None and mat2 is None:
                    result[i, j] = mat1
                elif mat1 is None and mat2 is not None:
                    result[i, j] = mat2
                else:
                    result[i, j] = None
            return result

        if isspmatrix(other):
            # Note: this can be supported if setup() has been called todo?
            raise NotImplementedError('Operation not supported by MPIBlockMatrix')

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __radd__(self, other):  # other + self
        return self.__add__(other)

    def __sub__(self, other):

        # ToDo: this might not be needed
        self._assert_setup()
        m, n = self.bshape
        result = self.copy_structure()

        rank = self._mpiw.Get_rank()

        if isinstance(other, MPIBlockMatrix):

            # ToDo: this might not be needed
            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1 - mat2
                elif mat1 is not None and mat2 is None:
                    result[i, j] = mat1
                elif mat1 is None and mat2 is not None:
                    result[i, j] = -mat2
                else:
                    result[i, j] = None
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1 - mat2
                elif mat1 is not None and mat2 is None:
                    result[i, j] = mat1
                elif mat1 is None and mat2 is not None:
                    result[i, j] = -mat2
                else:
                    result[i, j] = None
            return result

        if isspmatrix(other):
            # Note: this can be supported if setup() has been called todo?
            raise NotImplementedError('Operation not supported by MPIBlockMatrix')

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __rsub__(self, other):

        # ToDo: this might not be needed
        self._assert_setup()
        m, n = self.bshape
        result = self.copy_structure()

        rank = self._mpiw.Get_rank()

        if isinstance(other, MPIBlockMatrix):

            # ToDo: this might not be needed
            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat2 - mat1
                elif mat1 is not None and mat2 is None:
                    result[i, j] = -mat1
                elif mat1 is None and mat2 is not None:
                    result[i, j] = mat2
                else:
                    result[i, j] = None
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat2 - mat1
                elif mat1 is not None and mat2 is None:
                    result[i, j] = -mat1
                elif mat1 is None and mat2 is not None:
                    result[i, j] = mat2
                else:
                    result[i, j] = None
            return result

        if isspmatrix(other):
            # Note: this can be supported if setup() has been called todo?
            raise NotImplementedError('Operation not supported by MPIBlockMatrix')

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __mul__(self, other):

        self._assert_setup()
        m, n = self.bshape
        result = self.copy_structure()

        if isinstance(other, BlockVector):
            rank = self._mpiw.Get_rank()
            m, n = self.bshape
            assert n == other.nblocks, 'Dimension mismatch'
            assert not other.has_none, 'Block vector must not have none entries'
            assert np.compress(self._row_type == MULTIPLE_OWNER,
                               self._row_type).size == 0, \
                'Matrix-vector multiply only supported for ' \
                'matrices with single rank owner in each row.' \
                'Call pynumero.sparse.multiply instead or modify matrix ownership'

            # Note: this relies on the assertion above
            rank_ownership = np.empty(m, dtype=np.int64)
            for i in range(m):
                rank_ownership[i] = -1
                if self._row_type[i] != ALL_OWN_IT:
                    for j in range(n):
                        owner = self._rank_owner[i, j]
                        if owner != rank_ownership[i]:
                            rank_ownership[i] = owner
                            break

            result = MPIBlockVector(m, rank_ownership, self._mpiw)
            for i in range(m):
                row_owner = rank_ownership[i]
                if row_owner == rank  or row_owner < 0:
                    result[i] = np.zeros(self._brow_lengths[i])
                    for j in range(n):
                        x = other[j]
                        if self[i, j] is not None:
                            result[i] += self[i, j] * x
            return result

        if isinstance(other, MPIBlockVector):
            rank = self._mpiw.Get_rank()
            m, n = self.bshape
            assert n == other.nblocks, 'Dimension mismatch'
            assert not other.has_none, 'Block vector must not have none entries'
            assert np.compress(self._row_type == MULTIPLE_OWNER,
                               self._row_type).size == 0, \
                'Matrix-vector multiply only supported for ' \
                'matrices with single rank owner in each row.' \
                'Call pynumero.sparse.multiply instead or modify matrix ownership'

            # Note: this relies on the assertion above
            rank_ownership = np.empty(m, dtype=np.int64)
            for i in range(m):
                rank_ownership[i] = -1
                if self._row_type[i] != ALL_OWN_IT:
                    for j in range(n):
                        owner = self._rank_owner[i, j]
                        if owner != rank_ownership[i]:
                            rank_ownership[i] = owner
                            break

            result = MPIBlockVector(m, rank_ownership, self._mpiw)
            raise NotImplementedError('Operation not supported yet')

        if np.isscalar(other):
            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j] * other
            return result
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __rmul__(self, other):

        self._assert_setup()
        m, n = self.bshape
        result = self.copy_structure()

        if np.isscalar(other):
            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j] * other
            return result
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __pow__(self, other):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __truediv__(self, other):

        self._assert_setup()
        m, n = self.bshape
        result = self.copy_structure()

        if np.isscalar(other):
            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j] / other
            return result
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __floordiv__(self, other):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __iadd__(self, other):

        # ToDo: this might not be needed
        self._assert_setup()
        m, n = self.bshape

        if isinstance(other, MPIBlockMatrix):
            # ToDo: this might not be needed
            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    self[i, j] = mat1 + mat2
                elif mat1 is None and mat2 is not None:
                    self[i, j] = mat2
            return self

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    self[i, j] = mat1 + mat2
                elif mat1 is None and mat2 is not None:
                    self[i, j] = mat2

            return self

        if isspmatrix(other):
            # Note: this can be supported if setup() has been called todo?
            raise NotImplementedError('Operation not supported by MPIBlockMatrix')

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __isub__(self, other):

        # ToDo: this might not be needed
        self._assert_setup()
        m, n = self.bshape

        if isinstance(other, MPIBlockMatrix):
            # ToDo: this might not be needed
            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    self[i, j] = mat1 - mat2
                elif mat1 is None and mat2 is not None:
                    self[i, j] = -mat2
            return self

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]
                if mat1 is not None and mat2 is not None:
                    self[i, j] = mat1 - mat2
                elif mat1 is None and mat2 is not None:
                    self[i, j] = -mat2

            return self

        if isspmatrix(other):
            # Note: this can be supported if setup() has been called todo?
            raise NotImplementedError('Operation not supported by MPIBlockMatrix')

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __imul__(self, other):

        self._assert_setup()
        m, n = self.bshape

        if np.isscalar(other):
            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    self[i, j] = self[i, j] * other
            return self
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __itruediv__(self, other):

        self._assert_setup()
        m, n = self.bshape

        if np.isscalar(other):
            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    self[i, j] = self[i, j] / other
            return self
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __neg__(self):

        ii, jj = np.nonzero(self._owned_mask)
        for i, j in zip(ii, jj):
            if not self._block_matrix.is_empty_block(i, j):
                self[i, j] = -self[i, j]
        return self

    def __abs__(self):

        ii, jj = np.nonzero(self._owned_mask)
        for i, j in zip(ii, jj):
            if not self._block_matrix.is_empty_block(i, j):
                self[i, j] = self[i, j].__abs__()
        return self

    def __eq__(self, other):

        self._assert_setup() # needed for the nones
        m, n = self.bshape
        result = self.copy_structure()

        if isinstance(other, MPIBlockMatrix):

            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__eq__(mat2)
                elif mat1 is not None and mat2 is None:
                    result[i, j] = mat1.__eq__(0.0)
                elif mat1 is None and mat2 is not None:
                    result[i, j] = mat2.__eq__(0.0)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__eq__(0.0)
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__eq__(mat2)
                elif mat1 is not None and mat2 is None:
                    result[i, j] = mat1.__eq__(0.0)
                elif mat1 is None and mat2 is not None:
                    result[i, j] = mat2.__eq__(0.0)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__eq__(0.0)
            return result

        if np.isscalar(other):

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j].__eq__(other)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__eq__(other)
            return result

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __ne__(self, other):

        self._assert_setup() # needed for the nones
        m, n = self.bshape
        result = self.copy_structure()

        if isinstance(other, MPIBlockMatrix):

            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__ne__(mat2)
                elif mat1 is not None and mat2 is None:
                    result[i, j] = mat1.__ne__(0.0)
                elif mat1 is None and mat2 is not None:
                    result[i, j] = mat2.__ne__(0.0)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__ne__(0.0)
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__ne__(mat2)
                elif mat1 is not None and mat2 is None:
                    result[i, j] = mat1.__ne__(0.0)
                elif mat1 is None and mat2 is not None:
                    result[i, j] = mat2.__ne__(0.0)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__ne__(0.0)
            return result

        if np.isscalar(other):

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j].__ne__(other)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__ne__(other)
            return result

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __le__(self, other):

        self._assert_setup() # needed for the nones
        m, n = self.bshape
        result = self.copy_structure()

        if isinstance(other, MPIBlockMatrix):

            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__le__(mat2)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    if mat1 is not None and mat2 is None:
                        result[i, j] = mat1.__le__(mat)
                    elif mat1 is None and mat2 is not None:
                        result[i, j] = mat2.__le__(mat)
                    else:
                        result[i, j] = mat.__le__(mat)
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__le__(mat2)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    if mat1 is not None and mat2 is None:
                        result[i, j] = mat1.__le__(mat)
                    elif mat1 is None and mat2 is not None:
                        result[i, j] = mat2.__le__(mat)
                    else:
                        result[i, j] = mat.__le__(mat)
            return result

        if np.isscalar(other):

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j].__le__(other)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__le__(other)
            return result

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __lt__(self, other):

        self._assert_setup() # needed for the nones
        m, n = self.bshape
        result = self.copy_structure()

        if isinstance(other, MPIBlockMatrix):

            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__lt__(mat2)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    if mat1 is not None and mat2 is None:
                        result[i, j] = mat1.__lt__(mat)
                    elif mat1 is None and mat2 is not None:
                        result[i, j] = mat2.__lt__(mat)
                    else:
                        result[i, j] = mat.__lt__(mat)
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__lt__(mat2)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    if mat1 is not None and mat2 is None:
                        result[i, j] = mat1.__lt__(mat)
                    elif mat1 is None and mat2 is not None:
                        result[i, j] = mat2.__lt__(mat)
                    else:
                        result[i, j] = mat.__lt__(mat)
            return result

        if np.isscalar(other):

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j].__lt__(other)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__lt__(other)
            return result

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __ge__(self, other):

        self._assert_setup() # needed for the nones
        m, n = self.bshape
        result = self.copy_structure()

        if isinstance(other, MPIBlockMatrix):

            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__ge__(mat2)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    if mat1 is not None and mat2 is None:
                        result[i, j] = mat1.__ge__(mat)
                    elif mat1 is None and mat2 is not None:
                        result[i, j] = mat2.__ge__(mat)
                    else:
                        result[i, j] = mat.__ge__(mat)
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__ge__(mat2)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    if mat1 is not None and mat2 is None:
                        result[i, j] = mat1.__ge__(mat)
                    elif mat1 is None and mat2 is not None:
                        result[i, j] = mat2.__ge__(mat)
                    else:
                        result[i, j] = mat.__ge__(mat)
            return result

        if np.isscalar(other):

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j].__ge__(other)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__ge__(other)
            return result

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def __gt__(self, other):

        self._assert_setup() # needed for the nones
        m, n = self.bshape
        result = self.copy_structure()

        if isinstance(other, MPIBlockMatrix):

            other._assert_setup()

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            assert np.array_equal(self._rank_owner, other._rank_owner), \
                'MPIBlockMatrices must be distributed in same processors'

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__gt__(mat2)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    if mat1 is not None and mat2 is None:
                        result[i, j] = mat1.__gt__(mat)
                    elif mat1 is None and mat2 is not None:
                        result[i, j] = mat2.__gt__(mat)
                    else:
                        result[i, j] = mat.__gt__(mat)
            return result

        if isinstance(other, BlockMatrix):

            assert other.bshape == self.bshape, \
                'dimensions mismatch {} != {}'.format(self.bshape, other.bshape)

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                mat1 = self[i, j]
                mat2 = other[i, j]

                if mat1 is not None and mat2 is not None:
                    result[i, j] = mat1.__gt__(mat2)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    if mat1 is not None and mat2 is None:
                        result[i, j] = mat1.__gt__(mat)
                    elif mat1 is None and mat2 is not None:
                        result[i, j] = mat2.__gt__(mat)
                    else:
                        result[i, j] = mat.__gt__(mat)
            return result

        if np.isscalar(other):

            ii, jj = np.nonzero(self._owned_mask)
            for i, j in zip(ii, jj):
                if not self._block_matrix.is_empty_block(i, j):
                    result[i, j] = self[i, j].__gt__(other)
                else:
                    nrows = self._brow_lengths[i]
                    ncols = self._bcol_lengths[j]
                    mat = empty_matrix(nrows, ncols)
                    result[i, j] = mat.__gt__(other)
            return result

        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def sum(self, axis=None, dtype=None, out=None):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def mean(self, axis=None, dtype=None, out=None):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def diagonal(self, k=0):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def nonzero(self):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def setdiag(self, values, k=0):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix')

    def getcol(self, j):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix. TODO')

    def getrow(self, i):
        raise NotImplementedError('Operation not supported by MPIBlockMatrix. TODO')
