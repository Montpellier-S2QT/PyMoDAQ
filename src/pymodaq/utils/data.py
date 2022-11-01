# -*- coding: utf-8 -*-
"""
Created the 28/10/2022

@author: Sebastien Weber
"""
import copy
import numbers
from collections import OrderedDict, Iterable
import copy
import numpy as np
from typing import List, Union
import warnings
from time import time

from multipledispatch import dispatch
from pymodaq.utils.enums import BaseEnum, enum_checker
from pymodaq.utils.messenger import deprecation_msg
from pymodaq.utils.daq_utils import find_objects_in_list_from_attr_name_val

class DataShapeError(Exception):
    pass


class DataLengthError(Exception):
    pass


class DataDim(BaseEnum):
    """Enum for dimensionality representation of data"""
    Data0D = 0
    Data1D = 1
    Data2D = 2
    DataND = 3


class DataSource(BaseEnum):
    """Enum for source of data"""
    raw = 0
    calculated = 1


class DataDistribution(BaseEnum):
    """Enum for distribution of data"""
    uniform = 0
    spread = 1


class AxisBase:
    """Object holding info and data about physical axis of data

    Parameters
    ----------
    label: str
        The label of the axis, for instance 'time' for a temporal axis
    units: str
        The units of the data in the object, for instance 's' for seconds
    data: ndarray
        A 1D ndarray holding the data of the axis
    index: int
        a integer representing the index of the Data object this axis is related to
    """

    def __init__(self, label: str = '', units: str = '', data: np.ndarray = None, index: int = 0):
        super().__init__()
        self._size = None
        self._data = None
        self._index = None
        self._label = None
        self._units = None

        self.units = units
        self.label = label
        self.data = data
        self.index = index

    @property
    def label(self) -> str:
        """str: get/set the label of this axis"""
        return self._label

    @label.setter
    def label(self, lab: str):
        if not isinstance(lab, str):
            raise TypeError('label for the Axis class should be a string')
        self._label = lab

    @property
    def units(self) -> str:
        """str: get/set the units for this axis"""
        return self._units

    @units.setter
    def units(self, units: str):
        if not isinstance(units, str):
            raise TypeError('units for the Axis class should be a string')
        self._units = units

    @property
    def index(self) -> int:
        """int: get/set the index this axis corresponds to in a DataWithAxis object"""
        return self._index

    @index.setter
    def index(self, ind: int):
        self._check_index_valid(ind)
        self._index = ind

    @property
    def data(self):
        """np.ndarray: get/set the data of Axis"""
        return self._data

    @data.setter
    def data(self, dat: np.ndarray):
        self._check_data_valid(dat)
        self._data = dat
        self._size = dat.size

    @property
    def size(self) -> int:
        """int: the size/length of the 1D ndarray"""
        return self._size

    @staticmethod
    def _check_index_valid(index: int):
        if not isinstance(index, int):
            raise TypeError('index for the Axis class should be a positive integer')
        elif index < 0:
            raise ValueError('index for the Axis class should be a positive integer')

    @staticmethod
    def _check_data_valid(data):
        if data is None:
            raise ValueError(f'data for the Axis class should be a 1D numpy array')
        elif not isinstance(data, np.ndarray):
            raise TypeError(f'data for the Axis class should be a 1D numpy array')
        elif len(data.shape) != 1:
            raise ValueError(f'data for the Axis class should be a 1D numpy array')

    def create_linear_data(self, dim):
        """replace the axis data with a linear version of dim steps of size 1"""
        self.data = np.linspace(0, dim-1, dim)

    def __len__(self):
        return self.data.size

    def __getitem__(self, item):
        """For back compatibility when axis was a dict"""
        if hasattr(self, item):
            return getattr(self, item)

    def __repr__(self):
        return f'{self.__class__.__name__}: <label: {self.label}> - <units: {self.units}> - <index: {self.index}>'

    def __mul__(self, scale: numbers.Real):
        if isinstance(scale, numbers.Real):
            return self.__class__(data=self.data * scale, label=self.label, units=self.units, index=self.index)

    def __add__(self, offset: numbers.Real):
        if isinstance(offset, numbers.Real):
            return self.__class__(data=self.data + offset, label=self.label, units=self.units, index=self.index)

    def __eq__(self, other):
        eq = self.label == other.label
        eq = eq and (self.units == other.units)
        eq = eq and (np.any(np.abs(self.data - other.data) < 1e-10))
        eq = eq and (self.index == other.index)
        return eq


class Axis(AxisBase):
    """Axis object to be used to described physical axes of data"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class NavAxis(Axis):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        deprecation_msg('NavAxis should not be used anymore, please use Axis object with correct index.'
                        'The navigation index should be specified in the Data object')


class ScaledAxis(Axis):
    def __init__(self, label='', units='', offset=0, scaling=1, **kwargs):
        super().__init__(label=label, units=units, **kwargs)
        if not (isinstance(offset, float) or isinstance(offset, int)):
            raise TypeError('offset for the ScalingAxis class should be a float (or int)')
        self.offset = offset
        if not (isinstance(scaling, float) or isinstance(scaling, int)):
            raise TypeError('scaling for the ScalingAxis class should be a non null float (or int)')
        if scaling == 0 or scaling == 0.:
            raise ValueError('scaling for the ScalingAxis class should be a non null float (or int)')
        self.scaling = scaling

    @staticmethod
    def _check_data_valid(data):
        if data is not None:
            if not isinstance(data, np.ndarray):
                raise TypeError(f'data for the Axis class should be a 1D numpy array')
            elif len(data.shape) != 1:
                raise ValueError(f'data for the Axis class should be a 1D numpy array')

    @property
    def data(self):
        """np.ndarray: get/set the data of Axis"""
        return self._data

    @data.setter
    def data(self, data: np.ndarray):
        self._check_data_valid(data)
        self._data = data
        if data is not None:
            self._size = data.size
        else:
            self._size = 0


class ScalingOptions(dict):
    def __init__(self, scaled_xaxis: ScaledAxis, scaled_yaxis: ScaledAxis):
        assert isinstance(scaled_xaxis, ScaledAxis)
        assert isinstance(scaled_yaxis, ScaledAxis)
        self['scaled_xaxis'] = scaled_xaxis
        self['scaled_yaxis'] = scaled_yaxis


class DataLowLevel:
    """Abstract object for all Data Object

    Parameters
    ----------
    name: str
        the identifier of the data
    """

    def __init__(self, name: str):
        self._timestamp = time()
        self._name = name

    @property
    def name(self):
        """str: the identifier of the data"""
        return self._name

    @property
    def timestamp(self):
        """The timestamp of when the object has been created"""
        return self._timestamp

    def __getitem__(self, item):
        """For back compatibility when Data was a dict"""
        if hasattr(self, item):
            return getattr(self, item)


class DataBase(DataLowLevel):
    """Base object to store homogeneous data and metadata generated by pymodaq's objects. To be inherited for real data

    Parameters
    ----------
    name: str
        the identifier of these data
    source: DataSource or str
        Enum specifying if data are raw or processed (for instance from roi)
    dim: DataDim or str
        The identifier of the data type
    distribution: DataDistribution or str
        The distribution type of the data: uniform if distributed on a regular grid or spread if on specific
        unordered points
    data: list of ndarray
        The data the object is storing
    labels: list of str
        The labels of the data nd-arrays
    """

    def __init__(self, name: str, source: DataSource = None, dim: DataDim = None,
                 distribution: DataDistribution = DataDistribution['uniform'], data: List[np.ndarray] = None,
                 labels: List[str] = [], **kwargs):

        super().__init__(name=name)

        self._shape = None
        self._size = None
        self._data = None
        self._length = None
        self._labels = None
        self._dim = dim

        source = enum_checker(DataSource, source)
        self._source = source

        distribution = enum_checker(DataDistribution, distribution)
        self._distribution = distribution

        self.data = data  # dim consistency is actually checked within the setter method

        self._check_labels(labels)
        for key in kwargs:
            setattr(self, key, kwargs[key])

    def __repr__(self):
        return f'{self.__class__.__name__} <{self.name}> <{self.dim}> <{self.source}> <{self.shape}>'

    def __len__(self):
        return self.length

    @property
    def shape(self):
        """The shape of the nd-arrays"""
        return self._shape

    @property
    def size(self):
        """The size of the nd-arrays"""
        return self._size

    @property
    def dim(self):
        """DataDim: the enum representing the dimensionality of the stored data"""
        return self._dim

    @property
    def source(self):
        """DataSource: the enum representing the source of the data"""
        return self._source

    @property
    def distribution(self):
        """DataDistribution: the enum representing the distribution of the stored data"""
        return self._distribution

    @property
    def length(self):
        """The length of data. This is the length of the list containing the nd-arrays"""
        return self._length

    @property
    def labels(self):
        return self._labels

    def _check_labels(self, labels):
        while len(labels) < self.length:
            labels.append(f'CH{len(labels):02d}')
        self._labels = labels

    def get_data_index(self, index: int = 0):
        """Get the data by its index in the list"""
        return self.data[index]

    @staticmethod
    def _check_data_type(data: List[np.ndarray]) -> List[np.ndarray]:
        """make sure data is a list of nd-arrays"""
        is_valid = True
        if data is None:
            is_valid = False
        if not isinstance(data, list):
            # try to transform the data to regular type
            if isinstance(data, np.ndarray):
                warnings.warn(UserWarning(f'Your data should be a list of numpy arrays not just a single numpy array'
                                          f', wrapping them with a list'))
                data = [data]
            elif isinstance(data, numbers.Number):
                warnings.warn(UserWarning(f'Your data should be a list of numpy arrays not a scalar, wrapping it with a'
                                          f'list of numpy array'))
                data = [np.array([data])]
            else:
                is_valid = False
        if isinstance(data, list):
            if len(data) == 0:
                is_valid = False
            if not isinstance(data[0], np.ndarray):
                is_valid = False
            elif len(data[0].shape) == 0:
                is_valid = False
        if not is_valid:
            raise TypeError(f'Data should be an non-empty list of non-empty numpy arrays')
        return data

    def get_dim_from_data(self, data: List[np.ndarray]):
        """Get the dimensionality DataDim from data"""
        self._shape = data[0].shape
        self._size = data[0].size
        self._length = len(data)
        if len(self._shape) == 1 and self._size == 1:
            dim = DataDim['Data0D']
        elif len(self._shape) == 1 and self._size > 1:
            dim = DataDim['Data1D']
        elif len(self._shape) == 2:
            dim = DataDim['Data2D']
        else:
            dim = DataDim['DataND']
        return dim

    def _check_shape_dim_consistency(self, data: List[np.ndarray]):
        """Process the dim from data or make sure data and DataDim are coherent"""
        dim = self.get_dim_from_data(data)
        if self._dim is None:
            self._dim = dim
        else:
            if self._dim != dim:
                warnings.warn(UserWarning('The specified dimensionality is not coherent with the data shape'))
                self._dim = dim

    def _check_same_shape(self, data: List[np.ndarray]):
        """Check that all nd-arrays have the same shape"""
        for dat in data:
            if dat.shape != self.shape:
                raise DataShapeError('The shape of the ndarrays in data is not the same')

    @property
    def data(self):
        """List[np.ndarray]: get/set (and check) the data the object is storing"""
        return self._data

    @data.setter
    def data(self, data: List[np.ndarray]):
        data = self._check_data_type(data)
        self._check_shape_dim_consistency(data)
        self._check_same_shape(data)
        self._data = data


class DataWithAxes(DataBase):
    """Data object with Axis objects corresponding to underlying data nd-arrays

    Parameters
    ----------
    axes: list of Axis
        the list of Axis object for proper plotting, calibration ...
    nav_axes: tuple of int
        highlight which Axis in axes is Signal or Navigation axis depending on the content:
        For instance, nav_axes = (2,), means that the axis with index 2 in a at least 3D ndarray data is the first
        navigation axis
        For instance, nav_axes = (3,2), means that the axis with index 3 in a at least 4D ndarray data is the first
        navigation axis while the axis with index 2 is the second navigation Axis. Axes with index 0 and 1 are signal
        axes of 2D ndarray data
    """

    def __init__(self, *args, axes: List[Axis] = [], nav_axes: tuple = (), **kwargs):
        self._axes: List[Axis] = []
        axes = [axis for axis in axes]

        x_axis = kwargs.pop('x_axis') if 'x_axis' in kwargs else None
        y_axis = kwargs.pop('y_axis') if 'y_axis' in kwargs else None

        nav_x_axis = kwargs.pop('nav_x_axis') if 'nav_x_axis' in kwargs else None
        nav_y_axis = kwargs.pop('nav_y_axis') if 'nav_y_axis' in kwargs else None
        super().__init__(*args, **kwargs)

        self._check_axis(axes)
        self._manage_named_axes(axes, x_axis, y_axis, nav_x_axis, nav_y_axis)

        self._nav_indexes = nav_axes

    def _manage_named_axes(self, axes, x_axis=None, y_axis=None, nav_x_axis=None, nav_y_axis=None):
        """This method make sur old style Data is still compatible, especially when using x_axis or y_axis parameters"""
        modified = False
        if x_axis is not None:
            modified = True
            if self.dim == DataDim['Data1D'] and not self._has_get_axis_from_index(0)[0]:
                # in case of Data1D the x_axis corresponds to the first data dim
                index = 0
            elif self.dim == DataDim['Data2D'] and not self._has_get_axis_from_index(1)[0]:
                # in case of Data2D the x_axis corresponds to the second data dim (columns)
                index = 1
            axes.append(Axis(x_axis.label, x_axis.units, x_axis.data, index=index))

        if y_axis is not None:

            if self.dim == DataDim['Data2D'] and not self._has_get_axis_from_index(0)[0]:
                modified = True
                # in case of Data2D the y_axis corresponds to the first data dim (lines)
                axes.append(Axis(x_axis.label, x_axis.units, x_axis.data, index=index))

        if nav_x_axis is not None:
            if self.dim == DataDim['DataND']:
                modified = True
                # in case of Data2D the y_axis corresponds to the first data dim (lines)
                axes.append(Axis(x_axis.label, x_axis.units, x_axis.data, index=self._nav_indexes[0]))
        if modified:
            self._check_axis(axes)

    @property
    def axes(self):
        return self._axes

    def _check_axis(self, axes: List[Axis]):
        """Check all axis to make sure of their type and make sure their data are properly referring to the data index

        See Also
        --------
        :py:meth:`Axis.create_linear_data`
        """
        for ind, axis in enumerate(axes):
            if not isinstance(axis, Axis):
                raise TypeError(f'An axis of {self.__class__.name} should be an Axis object')
            if self.get_shape_from_index(axis.index) != axis.size:
                warnings.warn(UserWarning('The size of the axis is not coherent with the shape of the data. '
                                          'Replacing it with a linspaced version: np.array([0, 1, 2, ...])'))
                axes[ind].create_linear_data(self.get_shape_from_index(axis.index))
        self._axes = axes

    def get_shape_from_index(self, index: int) -> int:
        """Get the data shape at the given index"""
        if index > len(self.shape) or index < 0:
            raise IndexError('The specified index does not correspond to any data dimension')
        return self.shape[index]

    def is_axis_signal(self, index: int) -> bool:
        """Check if an axis defined by its index is considered signal or navigation"""
        return index in self._nav_indexes

    def is_axis_navigation(self, index: int) -> bool:
        """Check if an axis defined by its index is considered signal or navigation"""
        return index not in self._nav_indexes

    def _has_get_axis_from_index(self, index: int):
        """Check if the axis referred by a given data dimensionality index is present

        Returns
        -------
        bool: True if the axis has been found else False
        Axis or None: return the axis instance if has the axis else None
        """
        if index > len(self.shape) or index < 0:
            raise IndexError('The specified index does not correspond to any data dimension')
        for axis in self.axes:
            if axis.index == index:
                return True, axis
        return False, None

    def get_axis_from_index(self, index: int, create: bool = False) -> Axis:
        """Get the axis referred by a given data dimensionality index

        If the axis is absent, create a linear one to fit the data shape if parameter create is True

        Parameters
        ----------
        index: int
            The index referring to the data ndarray shape
        create: bool
            If True and the axis referred by index has not been found in axes, create one

        Returns
        -------
        Axis or None: return the axis instance if Data has the axis (or it has been created) else None

        See Also
        --------
        :py:meth:`Axis.create_linear_data`
        """
        has_axis, axis = self._has_get_axis_from_index(index)
        if not has_axis:
            if create:
                warnings.warn(
                    UserWarning(f'The axis requested with index {index} is not present, creating a linear one...'))
                axis = Axis(data=np.zeros((1,)), index=index)
                axis.create_linear_data(self.get_shape_from_index(index))
            else:
                warnings.warn(
                    UserWarning(f'The axis requested with index {index} is not present, returning None'))
        return axis


class DataRaw(DataWithAxes):
    """Specialized DataWithAxes set with source as 'raw'. To be used for raw data"""
    def __init__(self, *args,  **kwargs):
        if 'source' in kwargs:
            kwargs.pop('source')
        super().__init__(*args, source=DataSource['raw'], **kwargs)


class DataFromPlugins(DataRaw):
    """Specialized DataWithAxes set with source as 'raw'. To be used for raw data generated by plugins"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class DataCalculated(DataWithAxes):
    """Specialized DataWithAxes set with source as 'calculated'. To be used for processed/calculated data"""
    def __init__(self, *args, axes=[],  **kwargs):
        if 'source' in kwargs:
            kwargs.pop('source')
        super().__init__(*args, source=DataSource['calculated'], axes=axes, **kwargs)


class DataFromRoi(DataCalculated):
    """Specialized DataWithAxes set with source as 'calculated'.To be used for processed data from region of interest"""
    def __init__(self, *args, axes=[], **kwargs):
        super().__init__(*args, axes=axes, **kwargs)


class DataToExport(DataLowLevel):
    """Object to store all raw and calculated data in for later exporting, saving, sending signal...

    Includes methods to retrieve data from dim, source...
    Stored data have a unique identifier their name. If some data is appended with an existing name, it will replace
    the existing data

    Parameters
    ----------
    name: str
        The identifier of the exporting object
    data: list of DataWithAxes
        All the raw and calculated data to be exported

    Attributes
    ----------
    name
    timestamp
    data
    """

    def __init__(self, name, data: DataWithAxes = []):
        """

        Parameters
        ----------
        name
        data
        """
        super().__init__(name)
        if not isinstance(data, list):
            raise TypeError('Data stored in a DataToExport object should be as a list of objects'
                            ' inherited from DataWithAxis')
        for dat in data:
            self._check_data_type(dat)
        self._data: List[DataWithAxes] = [dat for dat in data]  # to make sure that if the original list is changed,
        # the change will not be applied in here

    def __repr__(self):
        return f'{self.__class__.__name__} <len:{len(self)}>'

    def __len__(self):
        return len(self.data)

    def get_data_from_dim(self, dim: DataDim) -> List[DataWithAxes]:
        """Get the data matching the given DataDim"""
        dim = enum_checker(DataDim, dim)
        selection = find_objects_in_list_from_attr_name_val(self.data, 'dim', dim, return_first=False)
        return [sel[0] for sel in selection]

    def get_data_from_name(self, name: str) -> List[DataWithAxes]:
        """Get the data matching the given name"""
        data, index = find_objects_in_list_from_attr_name_val(self.data, 'name', name)
        return data

    @property
    def data(self):
        """List[DataWithAxes]: get the data contained in the object"""
        return self._data

    @staticmethod
    def _check_data_type(data: DataWithAxes):
        """Make sure data is a DataWithAxes object or inherited"""
        if not isinstance(data, DataWithAxes):
            raise TypeError('Data stored in a DataToExport object should be objects inherited from DataWithAxis')


    @dispatch(list)
    def append(self, data: List[DataWithAxes]):
        for dat in data:
            self.append(dat)

    @dispatch(DataWithAxes)
    def append(self, data: DataWithAxes):
        """Append/replace DataWithAxes object to the data attribute

        Make sure only one DataWithAxes object with a given name is in the list
        """
        self._check_data_type(data)
        obj = self.get_data_from_name(data.name)
        if obj is not None:
            self._data.pop(self.data.index(obj))
        self._data.append(data)


if __name__ == '__main__':
    d1 = DataFromRoi(name=f'Hlineout_', data=[np.zeros((24,))],
                     x_axis=Axis(data=np.zeros((24,)),
                                 units='myunits',
                                 label='mylabel1'))
    d2 = DataFromRoi(name=f'Hlineout_', data=[np.zeros((12,))],
                     x_axis=Axis(data=np.zeros((12,)),
                                 units='myunits2',
                                 label='mylabel2'))
